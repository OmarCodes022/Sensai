"""State of the web interface: one creator, one active conversation, one turn at a time."""
import os
import shutil
import sqlite3
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from threading import Event, Lock, RLock

from sensai.chat import saved_sessions
from sensai.chat.context import ContextState, choose_window, ollama_window
from sensai.chat.prompts import load_system_prompt
from sensai.chat.saved_sessions import SessionRecorder, profile_block
from sensai.chat.session import ChatSession
from sensai.core.errors import SensaiError
from sensai.core.messages import Message
from sensai.core.ports import PolicyDenied, PortError, Profile, SessionSnapshot
from sensai.llm.ollama import OllamaClient
from sensai.llm.structured import OllamaStructuredClient
from sensai.memory.sqlite_store import StorageRepository
from sensai.sandbox import RUN_PYTHON, SandboxError, data_file_names, data_prompt, remove_stale_folders
from sensai.settings import Settings
from sensai.mcp_client import Catalogue as MCPCatalogue
from sensai.llm.embeddings import OllamaEmbeddingAdapter
from sensai.rag import DOCS_PROMPT, SEARCH_DOCS, DocLibrary
from sensai.campaign import CampaignStore
from sensai.export import Exporter
from sensai.chat.facts import DELETE_FACT, SAVE_FACT
from sensai.chat.questions import ASK_USER
from sensai.search import WEB_SEARCH
from sensai.security.file_tools import FILE_TOOLS, open_project
from sensai.guardrails import GuardedClient, GuardrailConfigError, load_guardrail
from sensai.tools import CALCULATE, tool_instructions
from sensai_web import session_view
from sensai_web.approvals import Approvals
from sensai_web.catalogue import Catalogue
from sensai_web.config import WebConfig
from sensai_web.datafiles import DataFolder
from sensai_web.errors import ApiError
from sensai_web.facts import make_memory
from sensai_web.scheduling import start as start_schedule
from sensai_web.websearch import make as make_search
from sensai_web.health import Health
from sensai_web.profile import clean_preferences
from sensai_web.tabs import TabLock
from sensai_web.times import TurnTimes
from sensai_web.usage import UsageCollector

LIST_LIMIT = 200


def make_client(settings: Settings, usage_sink=None) -> OllamaClient:
    return OllamaClient(settings.host, settings.timeout, usage_sink=usage_sink,
                        context_length=settings.context_length)


def make_embedding(cfg: WebConfig) -> OllamaEmbeddingAdapter:
    return OllamaEmbeddingAdapter(cfg.embed_model, host=cfg.host)


class StartupError(Exception):
    """A configuration problem found before the server starts (printed, exit status 1)."""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class ActiveSession:
    session: ChatSession
    recorder: SessionRecorder
    persona_id: str | None
    created_at: str
    updated_at: str
    prompt_tokens: int | None = None
    output_tokens: int | None = None
    last_prompt_tokens: int | None = None


class AppStore:
    """SessionRecorder's store: SQLite connections are per thread, so each call opens its own."""

    def __init__(self, app: "WebApp"):
        self._app = app

    def save(self, snapshot: SessionSnapshot) -> None:
        with self._app.creator_storage() as creator:
            creator.sessions.save(snapshot)

    def set_title(self, session_id: str, title: str) -> None:
        with self._app.creator_storage() as creator:
            creator.sessions.set_title(session_id, title)


def make_checker(cfg: WebConfig) -> OllamaStructuredClient:
    """The client /think uses to check a draft; one step's budget is one request."""
    return OllamaStructuredClient(cfg.host, cfg.operation_timeout, context_length=cfg.context_length)


class WebApp:
    def __init__(self, cfg: WebConfig, settings: Settings | None = None):
        source = None
        if cfg.context_length is None:  # M2: Ollama's choice for this computer, doubled at 4096 or less.
            window, source = choose_window(ollama_window(cfg.host, cfg.model))
            cfg = replace(cfg, context_length=window)
        self.cfg = cfg
        self.started = now()
        self.usage = UsageCollector()
        self.context = ContextState(cfg.context_length, source)  # M2: the window and what summaries saved
        self.approvals = Approvals()
        self.turn: Event | None = None
        self.mutex = RLock()
        self.run_lock = Lock()
        self.tabs = TabLock()
        self.times = TurnTimes(cfg.db_path, cfg.creator)
        self.data = DataFolder(cfg.data_dir)
        self.docs = DocLibrary(cfg.docs_dir, make_embedding(cfg), cfg.creator, cache_path=cfg.db_path, model=cfg.embed_model)
        self.model = cfg.model  # the page can change it while running
        self.checker = make_checker(cfg)
        try:  # File access (T4): on when .sensai/settings.json exists where Sensai starts.
            self.files = open_project(os.getcwd(), cfg.creator)
        except (PolicyDenied, PortError) as exc:
            raise StartupError(str(exc)) from None
        self.memory = make_memory(self)  # The brand fact sheet (M3); the model edits it through two tools.
        self.health = Health(cfg.host, cfg.model)
        self.meta_dir = tempfile.mkdtemp(prefix="sensai-web-")
        settings = (settings or Settings()).model_copy(update={"host": cfg.host, "context_length": cfg.context_length})
        self.mcp = MCPCatalogue(settings.mcp_config)
        self.mcp.reload()
        try:
            self.guard = load_guardrail(settings.guardrails_file, settings.brand_file)
        except GuardrailConfigError as exc:
            raise StartupError(str(exc)) from None
        # Every reply is checked line by line before the page sees it (EV2).
        self.chat_client = GuardedClient(make_client(settings, self.usage.add), self.guard)
        self.campaign = CampaignStore(settings.campaigns_dir)  # The weekly document (M4).
        self.pending_change = None  # An approved-section edit waiting for the creator's yes (A3).
        self.questions = Approvals()  # ask_user forms waiting for the page (X4).
        self.web = make_search(settings)  # Web search (T3), or None when switched off.
        self.rag_mode = settings.rag_mode  # advanced (R2) or basic (R1) document search
        self.exporter = Exporter(self.guard, settings.exports_dir)  # Private export (X3)
        self.title_client = make_client(settings)
        try:
            self.catalogue = Catalogue(cfg.personas_file)
            self.base_prompt = load_system_prompt(cfg.prompt_path)
        except (OSError, ValueError) as exc:
            raise StartupError(f"cannot load personas or prompt: {exc}") from None
        if cfg.data_dir and not os.path.isdir(cfg.data_dir):
            raise StartupError(f"data folder not found: {cfg.data_dir}")
        self.preferences: dict[str, str] = {}
        try:
            self._load_profile()
            self.active = self._initial_session()
            self.docs.sync()  # Whatever is in the documents folder starts indexing right away.
        except (PortError, sqlite3.Error, OSError, ValueError) as exc:
            raise StartupError(str(exc)) from None
        self.schedule_stop = Event()  # Scheduling (X5): last, its first run reads the profile and facts.
        try:
            self.scheduler = start_schedule(self, settings, GuardedClient(make_client(settings), self.guard))
        except ValueError as exc:
            raise StartupError(f"schedule: {exc}") from None

    # Storage

    @contextmanager
    def creator_storage(self):
        repository = StorageRepository(self.cfg.db_path)
        try:
            yield repository.for_creator(self.cfg.creator)
        finally:
            repository.close()

    def _load_profile(self) -> None:
        with self.creator_storage() as creator:
            if self.cfg.profile_file:
                creator.profiles.save(Profile("default", saved_sessions.load_profile_file(self.cfg.profile_file)))
            else:
                saved_sessions.seed_profile(creator.profiles)
            profile = creator.profiles.load("default")
        self.preferences = dict(profile.preferences) if profile else {}

    def save_profile(self, data: object) -> dict[str, str]:
        try:
            preferences = clean_preferences(data)
        except ValueError as exc:
            raise ApiError(400, "profile_invalid", str(exc)) from None
        with self.mutex:
            self.require_idle()
            with self.creator_storage() as creator:
                creator.profiles.save(Profile("default", preferences))
            self.preferences = preferences
            self.active.session.set_system_prompt(self.system_prompt(self.active.persona_id))
        return preferences

    # Prompt and sessions

    def tools_text(self) -> str:
        return tool_instructions((CALCULATE, RUN_PYTHON, SAVE_FACT, DELETE_FACT, *((SEARCH_DOCS,) if self.docs.enabled else ()),
                                  *(FILE_TOOLS if self.files is not None else ()), ASK_USER,
                                  *((WEB_SEARCH,) if self.web is not None else ()), *self.mcp.definitions()))

    def data_text(self) -> str:
        """The data file names for the model (as in the CLI), or "" without a readable data folder."""
        path = self.data.path
        if path is None or not os.path.isdir(path):
            return ""
        try:
            return data_prompt(data_file_names(path))
        except (SandboxError, OSError):
            return ""  # An unreadable folder never breaks a turn; the run itself reports it.

    def system_prompt(self, persona_id: str | None) -> str:
        """Shared rules, data file names, profile, persona, the search instructions while documents exist, then the tools."""
        prompt, block = self.base_prompt, profile_block(self.preferences)
        persona = self.catalogue.registry.get(persona_id) if persona_id else None
        docs = DOCS_PROMPT if self.docs.ready_count() > 0 else ""
        parts = (prompt, self.data_text(), block, self.memory.block(), persona.system_prompt if persona else "", docs)
        prompt = "\n\n".join(part for part in parts if part)
        tools = self.tools_text()
        return prompt if prompt.endswith(tools) else f"{prompt}\n\n{tools}"

    def refresh_prompt(self, active: "ActiveSession") -> list[str]:
        """Before a turn: notice document and data file changes, keep the prompt in step, return news to show."""
        self.docs.sync()
        notices = self.docs.notices()
        prompt = self.system_prompt(active.persona_id)
        if active.session.messages[0].content != prompt:
            active.session.messages[0] = Message(role="system", content=prompt)
        return notices

    def _active(self, session_id: str, persona_id: str | None, messages=(), title=None, saved=False,
                created_at: str | None = None, updated_at: str | None = None) -> ActiveSession:
        session = ChatSession(self.chat_client, self.model, self.system_prompt(persona_id))
        session.messages.extend(messages)
        recorder = SessionRecorder(AppStore(self), session_id, persona_id, title=title, saved=saved,
                                   messages=messages, write=lambda message: None)
        stamp = now()
        return ActiveSession(session, recorder, persona_id, created_at or stamp, updated_at or created_at or stamp)

    def _initial_session(self) -> ActiveSession:
        persona = self.cfg.persona
        if persona is not None and self.catalogue.registry.get(persona) is None:
            raise StartupError(f"unknown persona: {persona}")
        if self.cfg.session is None:
            return self.fresh_session(persona or self.catalogue.default_id())
        with self.creator_storage() as creator:
            snapshot = creator.sessions.load(self.cfg.session)
            meta = {s.id: s for s in creator.sessions.list()}.get(self.cfg.session)
        if snapshot is None:
            raise StartupError(f"unknown session: {self.cfg.session}")
        return self._resumed(snapshot, meta, persona)

    def fresh_session(self, persona_id: str | None) -> ActiveSession:
        with self.creator_storage() as creator:
            known = {s.id for s in creator.sessions.list()}
        return self._active(saved_sessions.new_session_id(known.__contains__), persona_id)

    def _resumed(self, snapshot: SessionSnapshot, meta, persona_id: str | None) -> ActiveSession:
        if persona_id is None and snapshot.persona_id is not None \
                and self.catalogue.registry.get(snapshot.persona_id) is not None:
            persona_id = snapshot.persona_id
        persona_id = persona_id or self.catalogue.default_id()
        messages = [m for m in snapshot.messages if m.role != "system"]
        return self._active(snapshot.id, persona_id, messages, meta.title if meta else None, True,
                            meta.created_at if meta else None, meta.updated_at if meta else None)

    def new_session(self) -> dict:
        with self.mutex:
            self.require_idle()
            self.active = self.fresh_session(self.active.persona_id)
            self.context.restart()
            return self.session_json(self.active)

    def resume(self, session_id: str) -> dict:
        with self.mutex:
            self.require_idle()
            with self.creator_storage() as creator:
                snapshot = creator.sessions.load(session_id)
                meta = {s.id: s for s in creator.sessions.list()}.get(session_id)
            if snapshot is None:
                raise ApiError(404, "not_found", f"unknown session: {session_id}")
            self.active = self._resumed(snapshot, meta, None)
            self.context.restart()
            return self.session_json(self.active)

    def set_persona(self, persona_id: object) -> str:
        if not isinstance(persona_id, str) or self.catalogue.registry.get(persona_id) is None:
            raise ApiError(404, "persona_unknown", f"unknown persona: {persona_id}")
        with self.mutex:
            self.require_idle()
            self.active.session.set_system_prompt(self.system_prompt(persona_id))
            self.active.persona_id = persona_id
            self.active.recorder.persona_changed(persona_id)
        return persona_id

    def save_persona(self, persona_id: str, data: object) -> str:
        """Add or edit a persona (written to the catalogue file); the open chat picks up the new wording."""
        with self.mutex:
            self.require_idle()
            try:
                result = self.catalogue.upsert(persona_id, data)
            except ValueError as exc:
                raise ApiError(400, "bad_persona", str(exc)) from None
            except OSError as exc:
                raise ApiError(500, "persona_unsaved", f"Could not save the personas: {exc}") from None
            self.active.session.set_system_prompt(self.system_prompt(self.active.persona_id))
        return result

    def delete_persona(self, persona_id: str) -> None:
        """Remove a persona; a chat that was using it falls back to the default one."""
        with self.mutex:
            self.require_idle()
            try:
                self.catalogue.remove(persona_id)
            except KeyError:
                raise ApiError(404, "persona_unknown", f"unknown persona: {persona_id}") from None
            except ValueError as exc:
                raise ApiError(400, "bad_persona", str(exc)) from None
            except OSError as exc:
                raise ApiError(500, "persona_unsaved", f"Could not save the personas: {exc}") from None
            if self.catalogue.registry.get(self.active.persona_id or "") is None:
                self.active.persona_id = self.catalogue.default_id()
                self.active.recorder.persona_changed(self.active.persona_id)
            self.active.session.set_system_prompt(self.system_prompt(self.active.persona_id))

    def session_json(self, active: ActiveSession) -> dict:
        messages = [m for m in active.session.messages if m.role != "system"]
        items = session_view.display_items(messages, active.persona_id,
                                           self.times.load(active.recorder.session_id),
                                           self.times.usage(active.recorder.session_id))
        return {
            "id": active.recorder.session_id, "saved": active.recorder.saved, "title": active.recorder.title,
            "persona": active.persona_id, "creator": self.cfg.creator, "items": items,
            "usage": {"prompt_tokens": active.prompt_tokens, "output_tokens": active.output_tokens,
                      "turns": sum(1 for item in items if item["kind"] == "user"),
                      "last_prompt_tokens": active.last_prompt_tokens},
            "created_at": active.created_at, "updated_at": active.updated_at,
        }

    def stored_session_json(self, session_id: str) -> dict:
        with self.mutex:
            if session_id == self.active.recorder.session_id:
                return self.session_json(self.active)
        with self.creator_storage() as creator:
            snapshot = creator.sessions.load(session_id)
            meta = {s.id: s for s in creator.sessions.list()}.get(session_id)
        if snapshot is None:
            raise ApiError(404, "not_found", f"unknown session: {session_id}")
        return self.session_json(self._resumed(snapshot, meta, None))

    def session_list(self) -> list[dict]:
        out = []
        with self.creator_storage() as creator:
            for summary in creator.sessions.list()[:LIST_LIMIT]:
                try:
                    snapshot = creator.sessions.load(summary.id)
                except SensaiError:
                    snapshot = None
                messages = list(snapshot.messages) if snapshot else []
                items = session_view.display_items(messages, None)
                title = summary.title or saved_sessions.display_title(None, messages) if snapshot else "(unreadable)"
                out.append({"id": summary.id, "title": title, "created_at": summary.created_at,
                            "updated_at": summary.updated_at, "persona": snapshot.persona_id if snapshot else None,
                            "messages": sum(1 for item in items if item["kind"] in ("user", "assistant"))})
        return out

    # One turn at a time

    def require_idle(self) -> None:
        if self.turn is not None:
            raise ApiError(429, "busy", "A reply is in progress. Stop it or wait for it to finish.")

    def begin_turn(self) -> tuple[Event, ActiveSession]:
        with self.mutex:
            self.require_idle()
            self.turn = Event()
            self.usage.reset()
            return self.turn, self.active

    def end_turn(self) -> None:
        with self.mutex:
            self.turn = None

    def stop_turn(self) -> bool:
        with self.mutex:
            stopping = self.turn is not None
            if stopping:
                self.turn.set()
            return stopping

    def close(self) -> None:
        self.schedule_stop.set()
        self.stop_turn()
        shutil.rmtree(self.meta_dir, ignore_errors=True)
        remove_stale_folders()
