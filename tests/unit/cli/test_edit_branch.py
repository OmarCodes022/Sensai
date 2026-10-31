"""/edit N <text>: continue from message N as a new saved branch, leaving the original unchanged."""

import pytest

from fakes import FakeClient, scripted_terminal
from sensai.chat import saved_sessions
from sensai.cli import main as cli
from sensai.core.cancellation import OperationCancelled
from sensai.core.messages import Message
from sensai.memory.sqlite_store import StorageRepository


@pytest.fixture(autouse=True)
def isolated(isolated_settings, tmp_path):
    (tmp_path / "prompt.txt").write_text("Shared rules", encoding="utf-8")


def chat(monkeypatch, tmp_path, client, inputs, *argv):
    monkeypatch.setattr(cli, "create_client", lambda settings: client)
    monkeypatch.setattr(cli, "TerminalInput", scripted_terminal(inputs))
    cli.main(["model", "--prompt", str(tmp_path / "prompt.txt"), "--db", str(tmp_path / "s.db"), *argv])


def stored(tmp_path):
    with StorageRepository(tmp_path / "s.db") as repository:
        sessions = repository.for_creator("default").sessions
        return {s.id: (s, sessions.load(s.id)) for s in sessions.list()}


def users(snapshot):
    return [m.content for m in snapshot.messages if m.role == "user"]


def test_edit_continues_from_message_n_as_a_new_branch_and_keeps_the_original(monkeypatch, tmp_path, capsys):
    client = FakeClient(["R1"], ["R2"], ["R3"], ["Playful!"])
    chat(monkeypatch, tmp_path, client, ["First", "Second", "Third", "/edit 2 More playful", "exit"])
    # The model saw only message 1 and the new text.
    assert client.calls[3][1:] == ["First", "R1", "More playful"]
    out = capsys.readouterr().out
    sessions = stored(tmp_path)
    original = next(i for i, (_, s) in sessions.items() if "Third" in users(s))
    branch = next(i for i in sessions if i != original)
    assert f"New branch {branch} from {original} ({original} is kept unchanged)." in out
    assert users(sessions[original][1]) == ["First", "Second", "Third"]
    assert users(sessions[branch][1]) == ["First", "More playful"]
    assert sessions[branch][0].title == f"{sessions[original][0].title} (branch)"


def test_a_branch_is_resumable_and_the_chat_goes_on_inside_it(monkeypatch, tmp_path, capsys):
    client = FakeClient(["R1"], ["R2"], ["Playful"], ["R4"])
    chat(monkeypatch, tmp_path, client, ["First", "Second", "/edit 2 Fun", "And more", "exit"])
    sessions = stored(tmp_path)
    original = next(i for i, (_, s) in sessions.items() if "Second" in users(s))
    branch = next(i for i in sessions if i != original)
    assert client.calls[3][1:] == ["First", "R1", "Fun", "Playful", "And more"]
    assert users(sessions[branch][1]) == ["First", "Fun", "And more"]
    assert users(sessions[original][1]) == ["First", "Second"]


@pytest.mark.parametrize("line", ["/edit 9 hello", "/edit x hello", "/edit 2", "/edit", "/edit 0 hi"])
def test_a_bad_edit_prints_an_error_and_changes_nothing(monkeypatch, tmp_path, capsys, line):
    client = FakeClient(["R1"], ["R2"])
    chat(monkeypatch, tmp_path, client, ["First", "Second", line, "exit"])
    out = capsys.readouterr().out
    assert ("usage: /edit <number> <new text>" in out) or ("there is no message" in out)
    assert len(client.calls) == 2 and len(stored(tmp_path)) == 1


def test_edit_with_no_messages_says_so(monkeypatch, tmp_path, capsys):
    chat(monkeypatch, tmp_path, FakeClient(), ["/edit 1 hello", "exit"])
    assert "there are no messages to edit yet" in capsys.readouterr().out


def test_an_interrupted_edit_saves_nothing_and_the_original_conversation_continues(monkeypatch, tmp_path, capsys):
    client = FakeClient(["R1"], ["R2"], ["partial", OperationCancelled("operation cancelled")], ["R4"])
    chat(monkeypatch, tmp_path, client, ["First", "Second", "/edit 1 Other", "Still here", "exit"])
    out = capsys.readouterr().out
    assert "Réponse interrompue" in out
    sessions = stored(tmp_path)
    assert len(sessions) == 1
    # The next message goes to the original conversation, with both original exchanges.
    assert client.calls[3][1:] == ["First", "R1", "Second", "R2", "Still here"]
    assert users(next(iter(sessions.values()))[1]) == ["First", "Second", "Still here"]


def test_messages_before_user_counts_only_the_creators_own_messages():
    tool = Message(role="user", content="Tool result from calculate:\n15")
    messages = [Message(role="system", content="s"), Message(role="user", content="a"),
                Message(role="assistant", content="x"), tool, Message(role="user", content="b")]
    assert [m.content for m in saved_sessions.messages_before_user(messages, 1)] == ["s"]
    assert [m.content for m in saved_sessions.messages_before_user(messages, 2)] == ["s", "a", "x", tool.content]
    assert saved_sessions.messages_before_user(messages, 3) is None
    assert saved_sessions.messages_before_user(messages, 0) is None


def test_a_branch_of_a_branch_keeps_a_single_suffix():
    assert saved_sessions.branch_title("Caption") == "Caption (branch)"
    assert saved_sessions.branch_title("Caption (branch)") == "Caption (branch)"
