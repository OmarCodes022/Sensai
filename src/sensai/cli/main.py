"""Command line interface."""
import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone
from math import isfinite
from time import monotonic
from collections.abc import Callable, Sequence
from typing import NamedTuple

from sensai.core.errors import SensaiError
from sensai.core.cancellation import CancellationToken, OperationCancelled, OperationTimedOut
from sensai.core.ports import PortError, Profile
from sensai.chat import saved_sessions
from sensai.chat.saved_sessions import SessionRecorder, display_title, profile_block
from sensai.cli.terminal import TerminalInput
from sensai.llm import create_client
from sensai.chat.prompts import load_system_prompt
from sensai.chat.personas import PersonaRegistry
from sensai.chat.session import ChatSession
from sensai.settings import Settings
from sensai.memory.sqlite_store import StorageError, StorageRepository

DEFAULT_DB_PATH = "sensai.sqlite3"


class PreparedChat(NamedTuple):
    prompt: str
    registry: PersonaRegistry
    base_prompt: str
    repository: StorageRepository
    recorder: SessionRecorder


def parse_args(settings: Settings, argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Chat with a local Ollama model.")
    p.add_argument("model", nargs="?", default=settings.model, help="model (or set SENSAI_MODEL)")
    p.add_argument("--prompt", default=settings.prompt_path,
                   help="system prompt file (default: the packaged prompt)")
    p.add_argument("--persona", help="persona identifier")
    p.add_argument("--personas-file", default=settings.personas_file,
                   help="JSON catalogue replacing the built-in personas")
    p.add_argument("--list-personas", action="store_true", help="list personas and exit")
    p.add_argument("--session", help="resume a saved session by ID")
    p.add_argument("--list-sessions", action="store_true", help="list saved sessions and exit")
    p.add_argument("--db", default=settings.db_path,
                   help=f"SQLite session database (default: {DEFAULT_DB_PATH})")
    p.add_argument("--creator", default=settings.creator,
                   help="creator key scoping sessions and profile (not authentication)")
    p.add_argument("--profile-file", default=settings.profile_file,
                   help="JSON object replacing the stored creator profile")
    p.add_argument("--host", default=settings.host, help="Ollama base URL")
    def positive_timeout(value):
        try:
            number = float(value)
        except ValueError:
            raise argparse.ArgumentTypeError("timeout must be a positive finite number") from None
        if not isfinite(number) or number <= 0:
            raise argparse.ArgumentTypeError("timeout must be a positive finite number")
        return number
    p.add_argument("--operation-timeout", type=positive_timeout,
                   default=settings.operation_timeout, help="maximum seconds per complete turn")
    args = p.parse_args(argv)
    args.persona_explicit = args.persona is not None
    if args.persona is None:
        args.persona = settings.persona
    if not args.model and not args.list_personas and not args.list_sessions:
        p.error("no model given: pass one or set SENSAI_MODEL in .env")
    return args


def repl(session: ChatSession, read: Callable[[str], str] = input, write=print,
         operation_timeout: float = 120.0, cancel_requested=None,
         persona_registry: PersonaRegistry | None = None,
         base_prompt: str | None = None, recorder: SessionRecorder | None = None) -> None:
    if base_prompt is None:
        base_prompt = session.messages[0].content
    while True:
        try:
            text = read("\n> ")
        except EOFError:
            write()
            return
        except KeyboardInterrupt:
            write()
            continue
        if text.strip().lower() in ("exit", "quit"):
            return
        command = text.strip().split(maxsplit=1)
        if command and command[0] == "/persona":
            if persona_registry is None:
                write("error: persona selection is unavailable")
            elif len(command) == 1:
                for persona_id, name in persona_registry.options:
                    write(f"{persona_id}: {name}")
            else:
                persona = persona_registry.get(command[1])
                if persona is None:
                    write(f"error: unknown persona: {command[1]}")
                else:
                    session.set_system_prompt(f"{base_prompt}\n\n{persona.system_prompt}")
                    write(f"Persona sélectionnée : {persona.id}")
                    if recorder is not None:
                        recorder.persona_changed(persona.id)
            continue
        token = CancellationToken(monotonic() + operation_timeout, cancel_requested)
        stream = session.send(text, token)
        completed = False
        try:
            for chunk in stream:
                write(chunk, end="", flush=True)
            write()
            completed = True
        except (KeyboardInterrupt, OperationCancelled):
            token.cancel()
            write("\nRéponse interrompue")
        except OperationTimedOut:
            write("\nDélai maximal dépassé")
        except ValueError:
            write("Please type something.")
        except SensaiError as e:
            write(f"error: {e}")
        finally:
            stream.close()
        if completed and recorder is not None:
            recorder.after_turn(session)


def _open_storage(args: argparse.Namespace):
    try:
        repository = StorageRepository(args.db or DEFAULT_DB_PATH)
    except (PortError, sqlite3.Error) as e:
        sys.exit(f"error: cannot open session database: {e}")
    try:
        return repository, repository.for_creator(args.creator)
    except PortError as e:
        repository.close()
        sys.exit(f"error: {e}")


def _listed_title(sessions, summary) -> str:
    if summary.title:
        return summary.title
    try:
        snapshot = sessions.load(summary.id)
    except StorageError:
        return "(titre illisible)"
    return display_title(None, snapshot.messages if snapshot else ())


def list_sessions(args: argparse.Namespace) -> None:
    """Print '<id>  <updated, UTC>  <title>' lines, most recently updated first."""
    if not os.path.exists(args.db or DEFAULT_DB_PATH):
        return
    repository, creator = _open_storage(args)
    try:
        for summary in creator.sessions.list():
            title = _listed_title(creator.sessions, summary)
            try:
                updated = datetime.fromisoformat(summary.updated_at).astimezone(timezone.utc)
                when = f"{updated:%Y-%m-%d %H:%M}"
            except (TypeError, ValueError):
                when = "????-??-?? ??:??"
            print(f"{summary.id}  {when}  {title}")
    except (PortError, sqlite3.Error, ValueError) as e:
        sys.exit(f"error: cannot list sessions: {e}")
    finally:
        repository.close()


def _resume(args, creator, registry, persona):
    """Resolve the session to record and its persona; errors exit before any client."""
    summaries = {summary.id: summary for summary in creator.sessions.list()}
    if args.session is None:
        return SessionRecorder(creator.sessions, saved_sessions.new_session_id(summaries.__contains__),
                               persona.id if persona else None), persona
    snapshot = creator.sessions.load(args.session)
    if snapshot is None:
        sys.exit(f"error: unknown session: {args.session} (see --list-sessions)")
    if not args.persona_explicit:
        persona = registry.get(snapshot.persona_id) if snapshot.persona_id is not None else None
        if snapshot.persona_id is not None and persona is None:
            sys.exit(f"error: persona '{snapshot.persona_id}' saved with session {args.session} "
                     "is no longer available; pass --persona")
    summary = summaries.get(args.session)
    recorder = SessionRecorder(
        creator.sessions, args.session, persona.id if persona else None,
        title=summary.title if summary else None, saved=True,
        messages=[m for m in snapshot.messages if m.role != "system"])
    return recorder, persona


def prepare_chat(args: argparse.Namespace) -> PreparedChat | None:
    """Load validated prompt, persona, profile and session before any client or tunnel."""
    try:
        registry = PersonaRegistry.from_file(args.personas_file)
    except (OSError, ValueError) as e:
        sys.exit(f"error: cannot load personas: {e}")
    if args.list_personas:
        for persona_id, name in registry.options:
            print(f"{persona_id}: {name}")
    if args.list_sessions:
        list_sessions(args)
    if args.list_personas or args.list_sessions:
        return
    persona = registry.get(args.persona) if args.persona is not None else None
    if args.persona is not None and persona is None and (args.persona_explicit
                                                         or args.session is None):
        sys.exit(f"error: unknown persona: {args.persona}")
    try:
        base_prompt = load_system_prompt(args.prompt)
    except OSError as e:
        sys.exit(f"error: cannot read system prompt: {e}")
    preferences = None
    if args.profile_file:
        try:
            preferences = saved_sessions.load_profile_file(args.profile_file)
        except (OSError, ValueError) as e:
            sys.exit(f"error: cannot load profile: {e}")
    repository, creator = _open_storage(args)
    try:
        recorder, persona = _resume(args, creator, registry, persona)
        if preferences is not None:
            creator.profiles.save(Profile("default", preferences))
        profile = creator.profiles.load("default")
    except PortError as e:
        repository.close()
        sys.exit(f"error: {e}")
    except sqlite3.Error as e:
        repository.close()
        sys.exit(f"error: session storage failed: {e}")
    except BaseException:
        repository.close()
        raise
    block = profile_block(profile.preferences if profile else {})
    if block:
        base_prompt = f"{base_prompt}\n\n{block}"
    prompt = base_prompt
    if persona is not None:
        prompt = f"{prompt}\n\n{persona.system_prompt}"
    return PreparedChat(prompt, registry, base_prompt, repository, recorder)


def run_chat(settings: Settings, args: argparse.Namespace, prepared: PreparedChat) -> None:
    prompt, registry, base_prompt, repository, recorder = prepared
    try:
        client = create_client(settings.model_copy(update={"host": args.host}))
        print(f"Chatting with {args.model}. Type '/persona' to list profiles or 'exit' to quit.")
        if recorder.saved:
            print(f"Session {recorder.session_id} — {display_title(recorder.title, recorder.messages)}")
        else:
            print(f"Session {recorder.session_id}")
        with TerminalInput() as terminal:
            def titler(first_user: str, first_answer: str) -> str | None:
                print("Titre de la session…")
                token = CancellationToken(
                    monotonic() + min(saved_sessions.TITLE_TIMEOUT, args.operation_timeout),
                    terminal.cancel_requested)
                return saved_sessions.generate_title(client, args.model, first_user,
                                                    first_answer, token)

            recorder.titler = titler
            session = ChatSession(client, args.model, prompt)
            session.messages.extend(recorder.messages)
            repl(session, read=terminal.read,
                 operation_timeout=args.operation_timeout,
                 cancel_requested=terminal.cancel_requested,
                 persona_registry=registry, base_prompt=base_prompt, recorder=recorder)
    finally:
        repository.close()


def main(argv: Sequence[str] | None = None) -> None:
    settings = Settings()
    args = parse_args(settings, argv)
    prepared = prepare_chat(args)
    if prepared is not None:
        run_chat(settings, args, prepared)
