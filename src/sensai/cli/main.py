"""Command line interface."""
import argparse
import json
import os
import sqlite3
import stat
import sys
from datetime import datetime, timezone
from math import isfinite
from time import monotonic
from collections.abc import Callable, Sequence
from functools import partial
from typing import NamedTuple

from sensai.core.errors import SensaiError
from sensai.core.cancellation import CancellationToken, OperationCancelled, OperationTimedOut
from sensai.core.ports import PortError, Profile, ToolCall
from sensai.chat import saved_sessions
from sensai.chat.saved_sessions import SessionRecorder, display_title, profile_block
from sensai.chat.reasoning import Section, think
from sensai.cli.approval import TerminalApproval, sanitize
from sensai.cli.terminal import TerminalInput
from sensai.llm import create_client
from sensai.llm.structured import OllamaStructuredClient
from sensai.chat.prompts import load_system_prompt
from sensai.chat.personas import PersonaRegistry
from sensai.chat.session import ChatSession
from sensai.settings import Settings
from sensai.memory.sqlite_store import StorageError, StorageRepository
from sensai.core.messages import Message
from sensai.sandbox import RUN_PYTHON, SandboxLimits, python_tool, remove_stale_folders
from sensai.tools import CALCULATE, ToolRegistry, calculate, run_with_tools, tool_instructions

DEFAULT_DB_PATH = "sensai.sqlite3"
MAX_SCRIPT_BYTES = 1024 * 1024


def _tool_prompt(prompt, registry):
    instructions = tool_instructions(registry.definitions())
    return prompt if prompt.endswith(instructions) else f"{prompt}\n\n{instructions}"


def _tools(read, approval=None, data_dir=None):
    registry = ToolRegistry(approval, read=read)
    registry.register(CALCULATE, calculate)
    registry.register(RUN_PYTHON, partial(python_tool, data_dir=data_dir), confirm=True)
    return registry


def _read_script(path):
    try:
        # Non-blocking open so a FIFO cannot hang the chat; only regular files are read.
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ValueError(f"{path} is not a regular file")
            with open(fd, "rb", closefd=False) as f:
                data = f.read(MAX_SCRIPT_BYTES + 1)
        finally:
            os.close(fd)
    except OSError as e:
        raise ValueError(f"cannot read {path}: {e.strerror or e}") from None
    if len(data) > MAX_SCRIPT_BYTES:
        raise ValueError(f"{path} is larger than 1 MiB")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError(f"{path} is not UTF-8 text") from None


def _sweep_quietly():
    """Remove folders of killed tool workers; a second Ctrl+C must not escape the REPL."""
    try:
        remove_stale_folders()
    except KeyboardInterrupt:
        pass


def _run_script(path, data_dir, token, write):
    """/run: the tool's timed worker path, without approval or chat history."""
    try:
        code = _read_script(path)
    except ValueError as e:
        write(f"error: {e}")
        return
    write(f"Running in the sandbox (limit {SandboxLimits().wall_seconds:g} s)…")
    registry = ToolRegistry()
    registry.register(RUN_PYTHON, partial(python_tool, data_dir=data_dir))
    try:
        result = registry.execute(ToolCall(RUN_PYTHON.name, {"code": code}), token)
    except (KeyboardInterrupt, OperationCancelled):
        token.cancel()
        _sweep_quietly()
        write("\nExécution interrompue")
    except OperationTimedOut:
        _sweep_quietly()
        write("\nDélai maximal dépassé")
    except SensaiError as e:
        write(f"error: {e}")
    else:
        write(result.output or f"error: {result.error}")


def _think(session, tool_registry, request, checker, new_token, write, recorder):
    """/think: show every step; only the request and the final answer join the chat."""
    tokens = []

    def token():
        tokens.append(new_token())
        return tokens[-1]

    tool_text, line_start, result = False, True, None

    def end_line():
        return "" if line_start else "\n"

    def show(item):
        nonlocal tool_text, line_start
        if isinstance(item, Section):
            write(end_line() + item.title)
            # Only the call or result line under Act/Observe is tool text, not the narration.
            tool_text, line_start = item.title in ("Act", "Observe"), True
            return
        if tool_text:
            item = sanitize(item, keep="\t\n")  # Tool output may hold control characters.
            tool_text = False
        if item:
            write(item, end="", flush=True)
            line_start = item.endswith("\n")

    # Tool rounds arrive through ``emit`` as they finish, before the next model request.
    stream = think(session, tool_registry, request, checker, new_token=token, emit=show)
    try:
        while True:
            try:
                show(next(stream))
            except StopIteration as stop:
                result = stop.value
                break
        if not line_start:
            write()
    except (KeyboardInterrupt, OperationCancelled):
        if tokens:
            tokens[-1].cancel()
        _sweep_quietly()  # A killed tool worker may not have removed its folder.
        write(end_line() + "Réponse interrompue")
    except OperationTimedOut:
        _sweep_quietly()
        write(end_line() + "Délai maximal dépassé")
    except SensaiError as e:
        write(f"{end_line()}error: {e}")
    finally:
        stream.close()
    if result is None:
        return
    session.messages.append(Message(role="user", content=request))
    session.messages.append(Message(role="assistant", content=result.answer))
    if recorder is not None:
        recorder.after_turn(session)


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
                   default=settings.operation_timeout,
                   help="maximum seconds per complete turn, and per step of a /think")
    args = p.parse_args(argv)
    args.persona_explicit = args.persona is not None
    args.data_dir = settings.data_dir or None
    if args.persona is None:
        args.persona = settings.persona
    if not args.model and not args.list_personas and not args.list_sessions:
        p.error("no model given: pass one or set SENSAI_MODEL in .env")
    return args


HISTORY_WIDTH = 100


def _history_line(text: str) -> str:
    lines = text.strip().splitlines()
    line = lines[0].strip() if lines else ""
    if len(line) > HISTORY_WIDTH:
        return line[:HISTORY_WIDTH].rstrip() + " …"
    return line + " …" if len(lines) > 1 else line


def _history(messages) -> str:
    lines = [f"{n}. {_history_line(text)}"
             for n, text in enumerate(saved_sessions.user_messages(messages), 1)]
    return "\n".join(lines) or "Aucun message dans cette session."


def repl(session: ChatSession, read: Callable[[str], str] = input, write=print,
         operation_timeout: float = 120.0, cancel_requested=None,
         persona_registry: PersonaRegistry | None = None,
         base_prompt: str | None = None, recorder: SessionRecorder | None = None,
         tool_registry: ToolRegistry | None = None, data_dir: str | None = None,
         checker=None) -> None:
    if base_prompt is None:
        base_prompt = session.messages[0].content
    if tool_registry is None:
        tool_registry = _tools(read)
    session.messages[0] = Message(role="system", content=_tool_prompt(
        session.messages[0].content, tool_registry))
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
        if command and command[0] == "/tools":
            for definition in tool_registry.definitions():
                write(f"{definition.name}: {definition.description}")
            continue
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
                    session.set_system_prompt(_tool_prompt(
                        f"{base_prompt}\n\n{persona.system_prompt}", tool_registry))
                    write(f"Persona sélectionnée : {persona.id}")
                    if recorder is not None:
                        recorder.persona_changed(persona.id)
            continue
        if command and command[0] == "/history":
            write(_history(session.messages) if len(command) == 1 else "usage: /history")
            continue
        if command and command[0] == "/think":
            if len(command) == 1:
                write("usage: /think <request>")
            elif checker is None:
                write("error: /think is unavailable")
            else:
                # Each model step gets its own deadline; one cancel callback stops them all.
                def step_token():
                    return CancellationToken(monotonic() + operation_timeout, cancel_requested)

                _think(session, tool_registry, command[1], checker, step_token, write, recorder)
            continue
        token = CancellationToken(monotonic() + operation_timeout, cancel_requested)
        if command and command[0] == "/run":
            if len(command) == 1:
                write("usage: /run <file.py>")
            else:
                _run_script(command[1], data_dir, token, write)
            continue

        def on_tool(call, result):
            if call.name == RUN_PYTHON.name:
                summary = result.error if result.error is not None else result.output
                write(f"Using tool: {call.name} · {(summary.splitlines() or [''])[0]}")
                return
            # Visible text before a block always ends a line: no extra newline.
            arguments = json.dumps(dict(call.arguments), ensure_ascii=False)
            # Lone surrogates from model JSON cannot be printed as UTF-8.
            arguments = arguments.encode("utf-8", "backslashreplace").decode("utf-8")
            write(f"Using tool: {call.name}({arguments})")

        stream = run_with_tools(session, tool_registry, text, token, on_tool=on_tool)
        completed = False
        try:
            for chunk in stream:
                write(chunk, end="", flush=True)
            write()
            completed = True
        except (KeyboardInterrupt, OperationCancelled):
            token.cancel()
            _sweep_quietly()  # A killed tool worker may not have removed its folder.
            write("\nRéponse interrompue")
        except OperationTimedOut:
            _sweep_quietly()
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
    if args.data_dir and not os.path.isdir(args.data_dir):
        sys.exit(f"error: data folder not found: {args.data_dir}")
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
            tool_registry = _tools(terminal.read, approval=TerminalApproval(terminal.read_key, print),
                                   data_dir=args.data_dir)
            def titler(first_user: str, first_answer: str) -> str | None:
                token = CancellationToken(
                    monotonic() + min(saved_sessions.TITLE_TIMEOUT, args.operation_timeout),
                    terminal.cancel_requested)
                return saved_sessions.generate_title(client, args.model, first_user,
                                                    first_answer, token)

            recorder.titler = titler
            # Same host as the chat client, so the SSH tunnel serves the check calls too.
            # Its HTTP timeout is the per-step budget: a check is one /think step.
            checker = OllamaStructuredClient(args.host, args.operation_timeout,
                                             context_length=settings.context_length)
            session = ChatSession(client, args.model, _tool_prompt(prompt, tool_registry))
            session.messages.extend(recorder.messages)
            repl(session, read=terminal.read,
                 operation_timeout=args.operation_timeout,
                 cancel_requested=terminal.cancel_requested,
                 persona_registry=registry, base_prompt=base_prompt, recorder=recorder,
                 tool_registry=tool_registry, data_dir=args.data_dir, checker=checker)
    finally:
        try:
            remove_stale_folders()
        finally:
            repository.close()


def main(argv: Sequence[str] | None = None) -> None:
    settings = Settings()
    args = parse_args(settings, argv)
    prepared = prepare_chat(args)
    if prepared is not None:
        run_chat(settings, args, prepared)
