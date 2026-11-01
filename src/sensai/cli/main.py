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

from sensai.core.errors import LLMError, SensaiError
from sensai.core.cancellation import CancellationToken, OperationCancelled, OperationTimedOut
from sensai.core.ports import ApprovalRequest, PolicyDenied, PortError, Profile, ToolCall
from sensai.chat import compression, saved_sessions
from sensai.chat.context import ContextState, choose_window, loaded_window, ollama_window, summary_cap
from sensai.cli.context_commands import compact, summarize
from sensai.cli.team import team_command
from sensai.chat.agents import brand_facts
from sensai.llm.ollama import OllamaClient
from sensai.chat.saved_sessions import SessionRecorder, display_title, profile_block
from sensai.core.errors import GuardrailRefused
from sensai.guardrails import GuardedClient, Guardrail, GuardrailConfigError, load_guardrail
from sensai.guardrails.rules import message_for
from sensai.security.file_tools import FILE_TOOLS, FileTools, open_project
from sensai.campaign import CampaignError, CampaignStore
from sensai.campaign import apply as apply_change, approve as approve_section, ask as ask_edit, overview, plan as plan_change
from sensai.campaign.edits import editable as campaign_editable
from sensai.guardrails.rules import Claims
from sensai.llm.structured import StructuredOutputError
from sensai.chat.blocks import split_block
from sensai.export import Exporter, ExportRefused
from sensai.rag_advanced import DocSearch, make_ranker
from sensai.search import WEB_SEARCH, SearchError, WebSearch, numbered, provider_for, search
from sensai.chat.questions import ASK_USER, TerminalForm
from sensai.chat.facts import DELETE_FACT, SAVE_FACT, FactMemory, with_facts
from sensai.chat.reasoning import Section, think
from sensai.cli.approval import TerminalApproval, sanitize
from sensai.cli.terminal import TerminalInput
from sensai.llm import create_client
from sensai.llm.structured import OllamaStructuredClient
from sensai.chat.prompts import load_system_prompt
from sensai.chat.personas import PersonaRegistry
from sensai.chat.session import ChatSession
from sensai.settings import Settings
from sensai.mcp_client import EXAMPLE_CONFIG, GUIDE_URL, Catalogue
from sensai.memory.sqlite_store import StorageError, StorageRepository
from sensai.core.messages import Message
from sensai.sandbox import (PYTHON_ATTEMPTS, RUN_PYTHON, SandboxError, SandboxLimits, data_file_names,
                            data_prompt, format_run, python_tool, remove_stale_folders, report_summary)
from sensai.tools import CALCULATE, ToolRegistry, calculate, run_with_tools, tool_instructions
from sensai.rag import (DOCS_PROMPT, SEARCH_DOCS, DocLibrary, add_command, docs_command, reindex_command,
                       remove_command, search_docs_handler)
from sensai.llm.embeddings import OllamaEmbeddingAdapter

DEFAULT_DB_PATH = "sensai.sqlite3"
MAX_SCRIPT_BYTES = 1024 * 1024
SUMMARY_WIDTH = 160


def _tool_prompt(prompt, registry):
    instructions = tool_instructions(registry.definitions())
    return prompt if prompt.endswith(instructions) else f"{prompt}\n\n{instructions}"


def _tools(read, approval=None, data_dir=None, permission=None):
    registry = ToolRegistry(approval, read=read)
    registry.register(CALCULATE, calculate)
    registry.register(RUN_PYTHON, partial(python_tool, data_dir=data_dir, permission=permission),
                      confirm=True, max_calls=PYTHON_ATTEMPTS)
    return registry

def _mcp_notice(text: str) -> str:
    return sanitize(text).replace("reload MCP", "use /mcp reload")


def _mcp_load(mcp: Catalogue, read, write) -> bool:
    """Reload; a config file the user has not trusted yet runs nothing until they say so."""
    changed = mcp.reload()
    if mcp.untrusted is None:
        return changed
    write(sanitize(f"This MCP config is not trusted yet: {mcp.config_path()}"))
    write(sanitize(f"Trusting it runs these commands in {mcp.untrusted['folder']}, with your environment,"))
    write("and they can load code from that folder:")
    for line in mcp.untrusted["commands"]:
        write(f"  {sanitize(line)}")
    try:
        answer = read("Trust this file and run them? [y/N] ")
    except (EOFError, KeyboardInterrupt):
        answer = ""
    if answer.strip().lower() in ("y", "yes", "o", "oui"):
        mcp.trust(mcp.untrusted["digest"])
        return mcp.reload()
    write("MCP tools stay off. Use /mcp reload to be asked again.")
    return changed


def _mcp_status(mcp: Catalogue, write) -> None:
    """Where the configuration is, how its servers are, and how to add one."""
    found = "" if mcp.config_found() else " (not found, so no MCP tools)"
    write(sanitize(f"MCP config: {mcp.config_path()}{found}"))
    if mcp.untrusted:
        write("Not trusted yet, so nothing has run. Use /mcp reload to review its commands.")
    for notice in mcp.notices():
        write(_mcp_notice(notice))
    write("To add a server:")
    write("1. Put your servers in that file. For example:")
    write(EXAMPLE_CONFIG.rstrip())
    write("2. Only add servers you trust: each command runs on this computer, with your environment.")
    write("   This example needs Sensai's Python environment active, and uv for the time server.")
    write("3. Run /mcp reload and trust the file, then /tools. Each call asks for your approval.")
    write(f"Full guide: {GUIDE_URL}")


def _mcp_reload(mcp: Catalogue, session: ChatSession, tool_registry: ToolRegistry, read, write) -> None:
    """Replace the MCP tools only; the conversation stays."""
    old_names = [d.name for d in mcp.definitions()]
    core = session.messages[0].content.removesuffix(tool_instructions(tool_registry.definitions())).rstrip()
    if _mcp_load(mcp, read, write):
        for name in old_names:
            tool_registry.unregister(name)
        mcp.register(tool_registry)
        # Not set_system_prompt: that marks a persona switch and re-sends the prompt on every turn.
        session.messages[0] = Message(role="system", content=_tool_prompt(core, tool_registry))
    for notice in mcp.notices():
        write(_mcp_notice(notice))
    if not mcp.untrusted:
        write("MCP configuration reloaded." if not mcp.error else "MCP reload failed.")


def _setup_docs(args, settings, tool_registry, searcher=None) -> DocLibrary | None:
    """The documents folder as a library that indexes itself in the background; None if switched off."""
    if not args.docs:
        return None
    embedding = OllamaEmbeddingAdapter(settings.embed_model, host=args.host)
    library = DocLibrary(args.docs, embedding, args.creator, cache_path=args.db or DEFAULT_DB_PATH,
                         model=settings.embed_model)
    handler = searcher(library) if searcher else partial(search_docs_handler, library=library)
    tool_registry.register(SEARCH_DOCS, handler, timeout=None)
    library.sync()
    return library


def _with_docs(prompt: str, on: bool, registry: ToolRegistry) -> str:
    """The system prompt with the search instructions present exactly while there are documents."""
    instructions = tool_instructions(registry.definitions())
    core = prompt.removesuffix(instructions).rstrip()
    core = core.replace(f"\n\n{DOCS_PROMPT}", "")
    return _tool_prompt(f"{core}\n\n{DOCS_PROMPT}" if on else core, registry)


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
    registry.register(RUN_PYTHON, partial(python_tool, data_dir=data_dir, report=format_run))
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
        return False
    session.messages.append(Message(role="user", content=request))
    session.messages.append(Message(role="assistant", content=result.answer))
    if recorder is not None:
        recorder.after_turn(session)
    return True


class PreparedChat(NamedTuple):
    prompt: str
    registry: PersonaRegistry
    base_prompt: str
    repository: StorageRepository
    recorder: SessionRecorder


def _positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a positive whole number") from None
    if number <= 0:
        raise argparse.ArgumentTypeError("must be a positive whole number")
    return number


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
    p.add_argument("--docs", default=settings.docs_dir,
                   help="folder of brand documents to search (default: data/docs; empty switches it off)")
    def positive_timeout(value):
        try:
            number = float(value)
        except ValueError:
            raise argparse.ArgumentTypeError("timeout must be a positive finite number") from None
        if not isfinite(number) or number <= 0:
            raise argparse.ArgumentTypeError("timeout must be a positive finite number")
        return number
    p.add_argument("--context-budget", type=_positive_int, default=settings.context_length,
                   help="context window in tokens, sent to Ollama as num_ctx; older messages are summarized at 80%% "
                        "(default: SENSAI_CONTEXT_LENGTH, else the window Ollama loads)")
    p.add_argument("--weekly-run", metavar="FOLDER",
                   help="prepare the week's posts, DM replies, report and calendar from FOLDER and exit")
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


def _parse_edit(argument: str, messages) -> tuple[int, str] | str:
    """(message number, new text) for /edit, or the error line to print."""
    usage = "usage: /edit <number> <new text>"
    number, _, text = argument.strip().partition(" ")
    if not number.isdecimal() or not text.strip():
        return usage
    count = len(saved_sessions.user_messages(messages))
    if not 1 <= int(number) <= count:
        return f"error: there is no message {number} (use /history: 1 to {count})" if count else \
            "error: there are no messages to edit yet."
    return int(number), text.strip()


def repl(session: ChatSession, read: Callable[[str], str] = input, write=print,
         operation_timeout: float = 120.0, cancel_requested=None,
         persona_registry: PersonaRegistry | None = None,
         base_prompt: str | None = None, recorder: SessionRecorder | None = None,
         tool_registry: ToolRegistry | None = None, data_dir: str | None = None,
         docs: DocLibrary | None = None, checker=None, memory: FactMemory | None = None,
         guard: Guardrail | None = None, files: FileTools | None = None,
         campaign: CampaignStore | None = None, approval=None, web: WebSearch | None = None,
         doc_search: DocSearch | None = None, exporter: Exporter | None = None,
         mcp: Catalogue | None = None, context: ContextState | None = None, summary_client=None, probe=None,
         team_facts=lambda: "") -> None:
    if base_prompt is None:
        base_prompt = session.messages[0].content
    if tool_registry is None:
        tool_registry = _tools(read)
    session.messages[0] = Message(role="system", content=_tool_prompt(
        session.messages[0].content, tool_registry))
    docs_on = False

    def refresh_docs() -> None:
        """Notice new, edited and removed documents; show what happened; keep the prompt in step."""
        nonlocal docs_on
        if docs is None:
            return
        docs.sync()
        for line in docs.notices():
            write(line)
        on = docs.ready_count() > 0
        if on != docs_on:
            docs_on = on
            session.messages[0] = Message(role="system", content=_with_docs(
                session.messages[0].content, on, tool_registry))

    def refresh_facts() -> None:
        """Keep the saved facts in the system message (replaced directly: no resend flag)."""
        if memory is not None:
            session.messages[0] = Message(role="system", content=with_facts(
                session.messages[0].content, memory.block(), tool_instructions(tool_registry.definitions()),
                DOCS_PROMPT))

    def settle_facts(completed: bool) -> None:
        """Write the facts the turn queued if it completed; drop them otherwise."""
        if memory is None:
            return
        if not completed:
            memory.drop()
            return
        try:
            lines = memory.commit()
        except (PortError, sqlite3.Error) as e:
            memory.drop()
            write(f"error: facts not saved: {e}")
            return
        for line in lines:
            write(line)
        if lines:
            refresh_facts()

    def screen(text: str) -> str | None:
        """The message as the model may see it (identifiers redacted), or None when it is refused."""
        if guard is None:
            return text
        decision = guard.inspect(text, "input")
        if not decision.allowed:
            write(f"Blocked before the model: {message_for(decision.reason)} ({decision.reason})")
            return None
        if decision.text != text:
            write(f"(sent as: \"{decision.text}\")")
        return decision.text

    attached: list[str] = []  # Files read with /read, sent with the next message.

    def file_command(name: str, argument: str) -> None:
        if files is None:
            write("File access is off (no .sensai/settings.json).")
        elif not argument:
            write(f"usage: {name} <path>")
        elif name == "/read":
            try:
                text = files.read(argument)
            except PortError as e:  # PolicyDenied included; never shows file contents.
                write(f"{'Permission denied' if isinstance(e, PolicyDenied) else 'error'}: {e} ({argument})")
                return
            attached.append(f"File {argument}:\n{text}")
            write(f"Read {len(text):,} characters from {argument} (sent with your next message)")
        else:
            reply = next((split_block(m.content)[0].strip() for m in reversed(session.messages) if m.role == "assistant"), "")
            if not reply:
                write("Nothing to save yet: no reply in this conversation.")
                return
            try:
                write(f"{files.save(argument, reply + chr(10))} {argument}")
            except PortError as e:
                write(f"{'Permission denied' if isinstance(e, PolicyDenied) else 'error'}: {e} ({argument})")

    def campaign_command(argument: str) -> None:
        """/campaign, /campaign approve <section>, /campaign <posts|calendar> <request>."""
        if campaign is None:
            write("error: the campaign document is unavailable")
            return
        try:
            doc = campaign.latest()
            word, _, rest = argument.partition(" ")
            if not word:
                for line in overview(doc):
                    write(line)
            elif word == "approve":
                export_campaign(approve_section(campaign, doc, rest.strip()))
                write(f"{rest.strip().capitalize()} approved: later edits ask for confirmation first.")
            else:
                edit_section(doc, word, rest.strip())
        except CampaignError as e:
            write(f"error: {e}")

    def export_campaign(doc) -> None:
        """The private export follows every saved change (no question: it never leaves this computer)."""
        if exporter is None:
            return
        try:
            write(f"Exported campaign: {', '.join(exporter.campaign(doc))}")
        except ExportRefused as e:
            write(f"Campaign not exported: the guardrails refused it ({e}). The previous export is unchanged.")
        except OSError as e:
            write(f"error: campaign not exported: {e.strerror or e}")

    def export_all() -> None:
        if exporter is None:
            write("error: export is unavailable")
            return
        session_id = recorder.session_id if recorder is not None else "current"
        title = (recorder.title if recorder is not None else None) or display_title(None, session.messages[1:])
        try:
            write(f"Conversation: {', '.join(exporter.session(session_id, title, session.messages))}")
        except ExportRefused as e:
            write(f"Conversation not exported: the guardrails refused it ({e}).")
        except OSError as e:
            write(f"error: conversation not exported: {e.strerror or e}")
        if campaign is None or not campaign.has_any():
            write("No campaign yet: only the conversation was exported.")
        else:
            export_campaign(campaign.latest())

    def edit_section(doc, section: str, request: str) -> None:
        campaign_editable(doc, section)
        if not request:
            write(f"usage: /campaign {section} <what to change>")
            return
        claims = guard.claims if guard is not None else Claims()
        try:
            edit = ask_edit(checker, session.model, doc, section, request, claims)
        except (StructuredOutputError, LLMError) as e:
            write(f"error: no valid edit from the model ({e}); nothing changed.")
            return
        change = plan_change(doc, section, edit, claims)
        part = getattr(doc.sections, section)
        if part.status == "approved":  # A3: an approved section changes only after an explicit yes.
            content = "\n".join([f"Before:  {change.before!r}" if change.before is not None else "Before:  (nothing)",
                                 f"After:   {change.after!r}" if change.after is not None else "After:   (removed)"])
            request_ = ApprovalRequest(change.action, campaign.path(doc.week), f"{section.capitalize()} are approved", content)
            if approval is None or not approval.request(request_).approved:
                write("Nothing changed.")
                return
        write(f"{section.capitalize()}: {change.action}")
        write(f"Saved {apply_change(campaign, change)}")
        export_campaign(change.doc)

    refresh_facts()
    while True:
        refresh_docs()
        if memory is not None:
            memory.drop()
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
        if command and command[0] == "/mcp":
            if mcp is None:
                write("MCP is unavailable.")
            elif len(command) == 1:
                _mcp_status(mcp, write)
            elif command[1].strip() == "reload":
                _mcp_reload(mcp, session, tool_registry, read, write)
            else:
                write("usage: /mcp [reload]")
            continue
        if command and command[0] == "/tools":
            for definition in tool_registry.definitions():
                write(sanitize(f"{definition.name}: {definition.description}"))
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
                    session.set_system_prompt(_with_docs(
                        _tool_prompt(f"{base_prompt}\n\n{persona.system_prompt}", tool_registry), docs_on, tool_registry))
                    refresh_facts()
                    write(f"Persona sélectionnée : {persona.id}")
                    if recorder is not None:
                        recorder.persona_changed(persona.id)
            continue
        if command and command[0] == "/search":
            query = command[1].strip() if len(command) > 1 else ""
            if not query:
                write("usage: /search <query>")
            elif web is None:
                write("Web search is not available.")
            else:
                try:
                    found = search(query, web.provider, web.key)
                except SearchError as e:
                    write(f"Web search unavailable: {e}")
                else:
                    write(numbered(found) if found else f"No web results for {query!r}.")
            continue
        if command and command[0] == "/export":
            export_all()
            continue
        if command and command[0] == "/campaign":
            campaign_command(command[1].strip() if len(command) > 1 else "")
            continue
        if command and command[0] in ("/read", "/save"):
            file_command(command[0], command[1].strip() if len(command) > 1 else "")
            continue
        if command and command[0] in ("/context", "/compact"):
            if context is None:
                write("error: the context budget is unavailable")
            elif command[0] == "/context":
                write(context.report())
            else:
                compact(session, context, write, recorder,
                        CancellationToken(monotonic() + operation_timeout, cancel_requested), summary_client)
            continue
        if command and command[0] == "/facts":
            for line in (memory.listing() if memory is not None else ["error: the fact sheet is unavailable"]):
                write(line)
            continue
        if command and command[0] == "/history":
            write(_history(session.messages) if len(command) == 1 else "usage: /history")
            continue
        if command and command[0] == "/think":
            if len(command) == 1:
                write("usage: /think <request>")
            elif checker is None:
                write("error: /think is unavailable")
            elif (request := screen(command[1])) is not None:
                # Each model step gets its own deadline; one cancel callback stops them all.
                def step_token():
                    return CancellationToken(monotonic() + operation_timeout, cancel_requested)

                settle_facts(_think(session, tool_registry, request, checker, step_token, write, recorder))
            continue
        if command and command[0] == "/team":
            if len(command) == 1:
                write("usage: /team <brief>")
            elif checker is None:
                write("error: /team is unavailable")
            elif (brief := screen(command[1])) is not None:
                def step_token():  # Each agent gets its own deadline; Ctrl+C stops the team.
                    return CancellationToken(monotonic() + operation_timeout, cancel_requested)

                team_command(session, brief, checker, team_facts(), guard, step_token, write, recorder)
            continue
        original = branch = None
        if command and command[0] == "/edit":
            edited = _parse_edit(command[1] if len(command) > 1 else "", session.messages)
            if isinstance(edited, str):
                write(edited)
                continue
            number, text = edited
            if (text := screen(text)) is None:
                continue
            original = list(session.messages)
            session.messages[:] = saved_sessions.messages_before_user(original, number)
            command = []  # The new text is a plain message, never a command.
            if recorder is not None:
                known = {s.id for s in recorder.store.list()}
                branch = recorder.branch(saved_sessions.new_session_id(known.__contains__),
                                         [m for m in original if m.role != "system"])
                write(f"New branch {branch.session_id} from {recorder.session_id} "
                      f"({recorder.session_id} is kept unchanged).")
        commands = ("/run", "/docs", "/reindex", "/add", "/remove")
        if original is None and not (command and command[0] in commands):
            if attached:
                text = "\n\n".join([*attached, text])
                attached.clear()
            if (text := screen(text)) is None:
                continue
        token = CancellationToken(monotonic() + operation_timeout, cancel_requested)
        if command and command[0] == "/run":
            if len(command) == 1:
                write("usage: /run <file.py>")
            else:
                _run_script(command[1], data_dir, token, write)
            continue
        if command and command[0] in ("/docs", "/reindex", "/add", "/remove"):
            if docs is None:
                write("Document search is off (SENSAI_DOCS is empty).")
            else:
                argument = command[1] if len(command) > 1 else ""
                if command[0] == "/add":
                    lines = add_command(docs, argument)
                elif command[0] == "/remove":
                    lines = remove_command(docs, argument)
                elif command[0] == "/reindex":
                    lines = reindex_command(docs)
                else:
                    lines = docs_command(docs, argument)
                for line in lines:
                    write(line)
                refresh_docs()
            continue

        refresh_docs()  # A document added a moment ago counts for this very question.
        if web is not None:
            web.results.clear()  # Sources are listed per answer.
        if doc_search is not None:
            doc_search.report = None

        def on_tool(call, result):
            if call.name == RUN_PYTHON.name:
                calls, limit = tool_registry.usage(call.name)
                if limit and calls > limit:
                    write(f"Using tool: {call.name} · Stopped after {limit} attempts")
                    return
                first, detail = report_summary(
                    result.error if result.error is not None else result.output)
                write(f"Using tool: {call.name} · Run {calls} · {sanitize(first)}")
                if detail is not None:
                    write(sanitize(detail)[:SUMMARY_WIDTH])
                return
            # Visible text before a block always ends a line: no extra newline.
            arguments = json.dumps(dict(call.arguments), ensure_ascii=False)
            # Lone surrogates from model JSON cannot be printed as UTF-8.
            arguments = arguments.encode("utf-8", "backslashreplace").decode("utf-8")
            write(f"Using tool: {call.name}({arguments})")

        if context is not None:
            context.start_turn()
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
        except GuardrailRefused as e:
            write(f"\nReply blocked: {e} ({e.reason})")
        except SensaiError as e:
            write(f"error: {e}")
        finally:
            stream.close()
        if original is not None and not completed:
            session.messages[:] = original  # An interrupted or failed edit leaves the conversation as it was.
        if completed and branch is not None:
            recorder = branch
        if completed and context is not None:
            # Count before the title or summary requests report their own usage.
            tokens = context.end_turn(session.messages)
            if context.after_summary:
                write(context.line(tokens))
        if completed and recorder is not None:
            recorder.after_turn(session)
        settle_facts(completed)
        if completed and doc_search is not None and doc_search.report is not None and doc_search.report.hits:
            write("Document sources:")
            for hit in doc_search.report.hits:
                relevance = f", relevance {hit['relevance']}/10" if hit["relevance"] is not None else ""
                write(f"[{hit['n']}] {hit['source']} ({hit['version']}){relevance}")
        if completed and web is not None and web.results:
            write("Sources:")
            for n, result in enumerate(web.results, 1):
                write(f"[{n}] {sanitize(result.title, keep='')} {sanitize(result.url, keep='')}"
                      + (f" ({result.date})" if result.date else ""))
        if completed and context is not None:
            if probe is not None:
                context.learn(probe)
            if compression.should_compress(tokens, context.budget):
                summarize(session, context, tokens, write, recorder,
                          CancellationToken(monotonic() + operation_timeout, cancel_requested), summary_client)


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
    if args.data_dir:
        # Names only, never contents; T26 will pass its permission policy here.
        try:
            base_prompt = f"{base_prompt}\n\n{data_prompt(data_file_names(args.data_dir))}"
        except SandboxError as e:
            sys.exit(f"error: {e}")
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
        else:
            saved_sessions.seed_profile(creator.profiles)
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
        try:
            guard = load_guardrail(settings.guardrails_file, settings.brand_file)
        except GuardrailConfigError as e:
            sys.exit(f"error: {e}")
        # M2: the window is --context-budget, else Ollama's choice for this computer (doubled at 4096 or less),
        # sent as num_ctx on every request.
        budget, source = args.context_budget, None
        if budget is None:
            budget, source = choose_window(ollama_window(args.host, args.model))
        settings = settings.model_copy(update={"host": args.host, "context_length": budget})
        raw_client = create_client(settings)
        client = GuardedClient(raw_client, guard)  # Every reply is checked line by line before it is shown.
        context = ContextState(budget, source)
        if hasattr(raw_client, "set_usage_sink"):
            raw_client.set_usage_sink(context.on_usage)
        summary_client = None
        if isinstance(raw_client, OllamaClient):  # The summary's own answer is capped at a quarter of the window.
            def summary_client(budget):
                return OllamaClient(args.host, settings.timeout, context_length=budget,
                                    num_predict=summary_cap(budget))
        print(f"Chatting with {args.model}. Type '/persona' to list profiles or 'exit' to quit.")
        if recorder.saved:
            print(f"Session {recorder.session_id} — {display_title(recorder.title, recorder.messages)}")
        else:
            print(f"Session {recorder.session_id}")
        with TerminalInput() as terminal:
            approval = TerminalApproval(terminal.read_key, print)  # Tools and approved campaign edits ask the same way.
            tool_registry = _tools(terminal.read, approval=approval, data_dir=args.data_dir)
            found: list[DocSearch] = []

            def advanced(library):  # R2: filter, rerank with the model, drop weak matches.
                ranker = make_ranker(OllamaStructuredClient(args.host, args.operation_timeout,
                                                            context_length=settings.context_length), args.model)
                found.append(DocSearch(library, ranker, on_search=lambda report: print(report.summary())))
                return found[-1]
            docs = _setup_docs(args, settings, tool_registry, advanced if settings.rag_mode == "advanced" else None)
            try:
                files = open_project(os.getcwd(), args.creator)
            except (PolicyDenied, PortError) as e:
                sys.exit(f"error: {e}")
            if files is not None:
                allow, deny = files.fs.summary
                print(f"File access on: {allow} allow rule{'s' * (allow != 1)}, {deny} deny rule{'s' * (deny != 1)} "
                      "(.sensai/settings.json)")
                for definition in FILE_TOOLS:  # In this process, with the loaded policy.
                    tool_registry.register(definition, getattr(files, definition.name), timeout=None)
            memory = FactMemory(repository.for_creator(args.creator).facts)
            tool_registry.register(SAVE_FACT, memory.save, timeout=None)  # In this process: the queue is here.
            tool_registry.register(DELETE_FACT, memory.delete, timeout=None)
            tool_registry.register(ASK_USER, TerminalForm(terminal.read, print), timeout=None)  # Reads the terminal itself.
            web = WebSearch(provider_for(settings.search_provider, settings.search_api_key), settings.search_api_key,
                            on_search=lambda q: print(f"Searching the web for: {q}"))
            if web.provider != "off":
                tool_registry.register(WEB_SEARCH, web, timeout=None)  # Keeps this turn's sources here.
            mcp = Catalogue(settings.mcp_config)
            _mcp_load(mcp, terminal.read, print)
            mcp.register(tool_registry)
            for notice in mcp.notices():
                print(_mcp_notice(notice))
            if mcp.servers or mcp.error:
                print("MCP configuration changes: use /mcp reload to refresh tools.")
            def titler(first_user: str, first_answer: str) -> str | None:
                token = CancellationToken(
                    monotonic() + min(saved_sessions.TITLE_TIMEOUT, args.operation_timeout),
                    terminal.cancel_requested)
                return saved_sessions.generate_title(raw_client, args.model, first_user,
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
                 tool_registry=tool_registry, data_dir=args.data_dir,
                 docs=docs, checker=checker, memory=memory, guard=guard, files=files,
                 campaign=CampaignStore(settings.campaigns_dir), approval=approval, web=web,
                 doc_search=found[0] if found else None, exporter=Exporter(guard, settings.exports_dir),
                 mcp=mcp, context=context, summary_client=summary_client,
                 team_facts=lambda: "\n".join(part for part in (brand_facts(settings.brand_file), memory.block()) if part),
                 probe=lambda: loaded_window(args.host, args.model) if isinstance(raw_client, OllamaClient) else None)
    finally:
        try:
            remove_stale_folders()
        finally:
            repository.close()


def main(argv: Sequence[str] | None = None) -> None:
    settings = Settings()
    args = parse_args(settings, argv)
    if args.weekly_run:
        from sensai.cli.weekly import weekly_main
        sys.exit(weekly_main(settings, args))
    prepared = prepare_chat(args)
    if prepared is not None:
        run_chat(settings, args, prepared)
