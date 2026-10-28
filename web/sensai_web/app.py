"""State of the web interface: one creator, one active conversation, one turn at a time."""
import os
import shutil
import sqlite3
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Event, Lock, RLock

from sensai.chat import saved_sessions
from sensai.chat.prompts import load_system_prompt
from sensai.chat.saved_sessions import SessionRecorder, profile_block
from sensai.chat.session import ChatSession
from sensai.core.errors import SensaiError
from sensai.core.ports import PortError, Profile, SessionSnapshot
from sensai.llm.ollama import OllamaClient
from sensai.memory.sqlite_store import StorageRepository
from sensai.sandbox import RUN_PYTHON, remove_stale_folders
from sensai.settings import Settings
from sensai.tools import CALCULATE, tool_instructions
from sensai_web import session_view
from sensai_web.approvals import Approvals
from sensai_web.catalogue import Catalogue
from sensai_web.config import WebConfig
from sensai_web.datafiles import DataFolder
from sensai_web.errors import ApiError
from sensai_web.health import Health
from sensai_web.profile import clean_preferences
from sensai_web.tabs import TabLock
from sensai_web.times import TurnTimes
from sensai_web.usage import UsageCollector

LIST_LIMIT = 200
TOOLS_TEXT = tool_instructions((CALCULATE, RUN_PYTHON))


def make_client(settings: Settings, usage_sink=None) -> OllamaClient:
    return OllamaClient(settings.host, settings.timeout, usage_sink=usage_sink,
                        context_length=settings.context_length)


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


class WebApp:
    def __init__(self, cfg: WebConfig, settings: Settings | None = None):
        self.cfg = cfg
        self.started = now()
        self.usage = UsageCollector()
        self.approvals = Approvals()
        self.turn: Event | None = None
        self.mutex = RLock()
        self.run_lock = Lock()
        self.tabs = TabLock()
        self.times = TurnTimes(cfg.db_path, cfg.creator)
        self.data = DataFolder(cfg.data_dir)
        self.health = Health(cfg.host, cfg.model)
        self.meta_dir = tempfile.mkdtemp(prefix="sensai-web-")
        settings = (settings or Settings()).model_copy(update={"host": cfg.host})
        self.chat_client = make_client(settings, self.usage.add)
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
        except (PortError, sqlite3.Error, OSError, ValueError) as exc:
            raise StartupError(str(exc)) from None

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

    def system_prompt(self, persona_id: str | None) -> str:
        prompt, block = self.base_prompt, profile_block(self.preferences)
        persona = self.catalogue.registry.get(persona_id) if persona_id else None
        prompt = "\n\n".join(part for part in (prompt, block, persona.system_prompt if persona else "") if part)
        return prompt if prompt.endswith(TOOLS_TEXT) else f"{prompt}\n\n{TOOLS_TEXT}"

    def _active(self, session_id: str, persona_id: str | None, messages=(), title=None, saved=False,
                created_at: str | None = None, updated_at: str | None = None) -> ActiveSession:
        session = ChatSession(self.chat_client, self.cfg.model, self.system_prompt(persona_id))
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
            return self.fresh_session(persona)
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
        messages = [m for m in snapshot.messages if m.role != "system"]
        return self._active(snapshot.id, persona_id, messages, meta.title if meta else None, True,
                            meta.created_at if meta else None, meta.updated_at if meta else None)

    def new_session(self) -> dict:
        with self.mutex:
            self.require_idle()
            self.active = self.fresh_session(self.active.persona_id)
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

    def session_json(self, active: ActiveSession) -> dict:
        messages = [m for m in active.session.messages if m.role != "system"]
        items = session_view.display_items(messages, active.persona_id,
                                           self.times.load(active.recorder.session_id))
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
        self.stop_turn()
        shutil.rmtree(self.meta_dir, ignore_errors=True)
        remove_stale_folders()
