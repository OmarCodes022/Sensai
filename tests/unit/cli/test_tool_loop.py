"""Tool turns through the real REPL, terminal reader and persistent sessions."""

import io
import os

import pytest

from fakes import FakeClient, scripted_terminal
from sensai.chat import saved_sessions
from sensai.chat.personas import PersonaRegistry
from sensai.chat.session import ChatSession
from sensai.cli import main as cli
from sensai.cli.terminal import TerminalInput
from sensai.core.cancellation import OperationCancelled
from sensai.core.errors import LLMError
from sensai.core.ports import ToolDefinition, ToolResult
from sensai.memory import sqlite_store
from sensai.memory.sqlite_store import StorageError, StorageRepository
from sensai.tools import ToolRegistry


pytestmark = pytest.mark.usefixtures("isolated_settings")
TOOL_CALL = '{"tool":"lookup","arguments":{}}'


def register_lookup(read, *, confirm=False, **_):
    registry = ToolRegistry(read=read)
    registry.register(ToolDefinition("lookup", "Look up a supplied value."),
                      lambda arguments, cancellation: ToolResult("7"),
                      timeout=None, confirm=confirm)
    return registry


def test_tools_and_persona_commands_do_not_call_model_or_duplicate_instructions(capsys):
    client = FakeClient(["Seven"])
    session = ChatSession(client, "model", "Shared rules")
    inputs = iter(["/tools", "/persona analyse", "/persona analyse", "/tools", "Q", "exit"])
    cli.repl(session, read=lambda _: next(inputs), persona_registry=PersonaRegistry.from_file())
    assert len(client.requests) == 1
    request = client.requests[0][1]
    assert [m.role for m in request] == ["system", "system", "user"]
    assert request[0] == request[1]  # Existing persona reminder immediately before the question.
    assert session.messages[0].content.count("Available tools (use only when needed):") == 1
    assert session.messages[0].content.count('"name": "calculate"') == 1
    assert [m.content for m in session.messages[1:]] == ["Q", "Seven"]
    assert capsys.readouterr().out.count("calculate: Calculate arithmetic") == 2


@pytest.mark.parametrize("fail_first_save", [False, True])
def test_whole_tool_turn_is_saved_resumed_and_titled_from_first_final_answer(
    monkeypatch, tmp_path, real_titles, fail_first_save
):
    database = tmp_path / "sessions.sqlite3"
    monkeypatch.setattr(cli, "_tools", register_lookup)
    monkeypatch.setattr(saved_sessions, "new_session_id", lambda exists: "k7f2qa")
    original_save = sqlite_store._SessionStore.save
    attempts = []

    def save(store, snapshot):
        attempts.append(snapshot)
        if fail_first_save and len(attempts) == 1:
            raise StorageError("disk full")
        return original_save(store, snapshot)

    monkeypatch.setattr(sqlite_store._SessionStore, "save", save)
    replies = [[TOOL_CALL], ["Seven"]]
    inputs = ["First question"]
    if fail_first_save:
        replies.append(["Next answer"])
        inputs.append("Next question")
    replies.append(["A useful title"])
    client = FakeClient(*replies)
    monkeypatch.setattr(cli, "create_client", lambda settings: client)
    monkeypatch.setattr(cli, "TerminalInput", scripted_terminal([*inputs, "exit"]))
    cli.main(["model", "--db", str(database)])
    assert [len(s.messages) for s in attempts] == ([4, 6] if fail_first_save else [4])
    assert [m.role for m in client.requests[0][1]] == ["system", "user"]
    assert client.requests[-1][1][0].content == saved_sessions.TITLE_PROMPT
    assert client.requests[-1][1][1].content == "Message : First question\n\nRéponse : Seven"
    with StorageRepository(database) as repository:
        store = repository.for_creator("default").sessions
        snapshot = store.load("k7f2qa")
        assert store.list()[0].title == "A useful title"
    assert [m.content for m in snapshot.messages[:4]] == [
        "First question", TOOL_CALL, "Tool result from lookup:\n7", "Seven",
    ]
    resumed = FakeClient(["Continued"])
    monkeypatch.setattr(cli, "create_client", lambda settings: resumed)
    monkeypatch.setattr(cli, "TerminalInput", scripted_terminal(["Continue", "exit"]))
    cli.main(["model", "--db", str(database), "--session", "k7f2qa"])
    assert len(resumed.requests) == 1
    request = resumed.requests[0][1]
    assert [m.role for m in request].count("system") == 1
    assert request[0].content.count("Available tools (use only when needed):") == 1
    assert tuple(request[1:-1]) == snapshot.messages
    assert request[-1].content == "Continue"


@pytest.mark.parametrize("failure", [OperationCancelled("cancelled"), LLMError("offline")])
def test_failed_final_reply_after_tool_saves_no_partial_turn(monkeypatch, tmp_path, failure, capsys):
    database = tmp_path / "sessions.sqlite3"
    client = FakeClient([TOOL_CALL], ["partial", failure])
    sessions = []

    def session(*args):
        sessions.append(ChatSession(*args))
        return sessions[-1]

    monkeypatch.setattr(cli, "ChatSession", session)
    monkeypatch.setattr(cli, "_tools", register_lookup)
    monkeypatch.setattr(cli, "create_client", lambda settings: client)
    monkeypatch.setattr(cli, "TerminalInput", scripted_terminal(["Question", "exit"]))
    cli.main(["model", "--db", str(database)])
    assert len(client.requests) == 2
    assert len(sessions[0].messages) == 1
    with StorageRepository(database) as repository:
        assert repository.for_creator("default").sessions.list() == ()
    output = capsys.readouterr().out
    assert output.count("Using tool: lookup") == 1
    assert TOOL_CALL not in output


def test_cli_approval_uses_actual_raw_terminal_reader(monkeypatch, tmp_path):
    master, slave = os.openpty()
    answers = iter([b"Question\r", b"OUi\r", b"7\r", b"exit\r"])

    class TerminalOutput(io.StringIO):
        def write(self, text):
            if text in ("\n> ", "Value: ") or text.startswith("Allow lookup("):
                os.write(master, next(answers))
            return super().write(text)

    output = TerminalOutput()
    client = FakeClient([TOOL_CALL], ["Seven"])

    def tools(read, **_):
        registry = ToolRegistry(read=read)

        def lookup(arguments, cancellation):
            assert cancellation.deadline is None
            return ToolResult(read("Value: "))

        registry.register(ToolDefinition("lookup", "Ask for a value."), lookup,
                          timeout=None, confirm=True)
        return registry

    monkeypatch.setattr(cli, "_tools", tools)
    monkeypatch.setattr(cli, "create_client", lambda settings: client)
    monkeypatch.setattr("builtins.input", lambda *args: pytest.fail("builtin input bypasses raw reader"))
    try:
        with os.fdopen(slave, "r", encoding="utf-8") as stdin:
            terminal = TerminalInput(stdin, output)
            assert terminal.interactive
            monkeypatch.setattr(cli, "TerminalInput", lambda: terminal)
            cli.main(["model", "--db", str(tmp_path / "sessions.sqlite3")])
    finally:
        os.close(master)
    assert len(client.requests) == 2
    assert client.requests[1][1][-1].content == "Tool result from lookup:\n7"
    assert "Allow lookup({})? [y/N] " in output.getvalue()
