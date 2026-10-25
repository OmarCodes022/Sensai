"""The /history REPL command: lists the creator's messages without contacting the model or saving."""

import io

import pytest

from fakes import FakeClient, FakeSessionStore, scripted_terminal
from sensai.chat import saved_sessions
from sensai.chat.personas import PersonaRegistry
from sensai.chat.saved_sessions import SessionRecorder
from sensai.chat.session import ChatSession
from sensai.core.messages import Message
from sensai.cli import main as cli
from sensai.cli.main import repl
from sensai.memory.sqlite_store import StorageRepository


@pytest.fixture(autouse=True)
def isolated(isolated_settings, tmp_path):
    (tmp_path / "prompt.txt").write_text("Shared rules", encoding="utf-8")


def run(session, inputs, **kwargs):
    reads = iter(inputs)
    output = io.StringIO()
    repl(session, read=lambda prompt: next(reads),
         write=lambda *args, **kw: print(*args, file=output, **kw), **kwargs)
    return output.getvalue()


def chat(monkeypatch, tmp_path, client, inputs, *argv):
    monkeypatch.setattr(cli, "create_client", lambda settings: client)
    monkeypatch.setattr(cli, "TerminalInput", scripted_terminal(inputs))
    cli.main(["model", "--prompt", str(tmp_path / "prompt.txt"),
              "--db", str(tmp_path / "s.db"), *argv])


def stored(tmp_path):
    with StorageRepository(tmp_path / "s.db") as repository:
        sessions = repository.for_creator("default").sessions
        return [(s, sessions.load(s.id)) for s in sessions.list()]


def test_empty_session_says_so():
    client = FakeClient()
    session = ChatSession(client, "model", "sys")
    assert run(session, ["/history", "exit"]) == "Aucun message dans cette session.\n"
    assert client.requests == []


def test_lists_only_user_messages_numbered_one_line_each():
    client = FakeClient(["Bonjour", " !"], ["Ligne 1\nLigne 2"], ["R3"])
    session = ChatSession(client, "model", "secret system")
    output = run(session, ["Salut", "Deux\nlignes", "x" * 120, "/history", "exit"])
    assert output.endswith(
        "R3\n"
        "1. Salut\n"
        "2. Deux …\n"
        f"3. {'x' * 100} …\n")
    assert "secret system" not in output
    assert "Bonjour" not in output.split("R3\n", 1)[1]


def test_matches_the_t34_example():
    session = ChatSession(FakeClient(["A"], ["B"], ["C"]), "model", "sys")
    output = run(session, ["Write an Instagram caption for the Night Cream launch",
                           "Make it shorter", "Add three hashtags", "/history", "exit"])
    assert output == ("A\nB\nC\n"
                      "1. Write an Instagram caption for the Night Cream launch\n"
                      "2. Make it shorter\n"
                      "3. Add three hashtags\n")


def test_tool_loop_protocol_messages_are_left_out():
    session = ChatSession(FakeClient(), "model", "sys")
    session.messages.extend([
        Message(role="user", content="Compte les mots"),
        Message(role="assistant", content='{"tool": "run_python", "arguments": {"code": "1"}}'),
        Message(role="user", content='Tool result from run_python:\n{"stdout": "1"}'),
        Message(role="assistant", content='{"tool": "run_python", "arguments": {}}'),
        Message(role="user", content="Tool error from run_python: boom\n"
                                     "Tool round limit reached. Give a final answer without tools."),
        Message(role="assistant", content="Voilà"),
        Message(role="user", content="Merci"),
    ])
    assert run(session, ["/history", "exit"]) == "1. Compte les mots\n2. Merci\n"


def test_persona_switch_system_prompt_is_not_shown():
    session = ChatSession(FakeClient(["R1"]), "model", "Base rules")
    output = run(session, ["/persona analyse", "Q1", "/history", "exit"],
                 persona_registry=PersonaRegistry.from_file(None), base_prompt="Base rules")
    history = output.split("Persona sélectionnée : analyse\n", 1)[1].split("R1\n", 1)[1]
    assert history == "1. Q1\n"
    assert session.messages[0].role == "system"
    assert session.messages[0].content not in history


class RecordingStore(FakeSessionStore):
    def __init__(self):
        super().__init__()
        self.writes = []

    def save(self, session):
        self.writes.append(session)
        super().save(session)

    def set_title(self, session_id, title):
        self.writes.append((session_id, title))


def test_history_does_not_contact_model_change_messages_or_record():
    client = FakeClient(["R1"])
    store = RecordingStore()
    titles = []
    recorder = SessionRecorder(store, "abc123", titler=lambda *args: titles.append(args) or "T")
    session = ChatSession(client, "model", "sys")
    reads = iter(["Q1", "/history", "/history foo", "exit"])
    snapshots = []

    def state():
        return tuple(session.messages), len(client.requests), list(store.writes), len(titles)

    def read(prompt):
        snapshots.append(state())
        return next(reads)

    repl(session, read=read, write=lambda *args, **kw: None, recorder=recorder)
    assert snapshots[1] == snapshots[2] == snapshots[3]
    messages, requests, writes, title_calls = snapshots[3]
    # With tools registered, repl appends the tool instructions to the system message.
    assert messages[0].content.startswith("sys")
    assert [m.content for m in messages[1:]] == ["Q1", "R1"]
    assert requests == 1 and title_calls == 1 and len(writes) == 2


def test_arguments_print_only_usage():
    client = FakeClient(["R1"])
    session = ChatSession(client, "model", "sys")
    output = run(session, ["Q1", "/history foo", "exit"])
    assert output == "R1\nusage: /history\n"
    assert len(client.requests) == 1


def test_resumed_session_shows_stored_turns_and_saves_nothing(
    monkeypatch, tmp_path, capsys, real_titles
):
    monkeypatch.setattr(saved_sessions, "new_session_id", lambda exists: "k7f2qa")
    chat(monkeypatch, tmp_path, FakeClient(["R1"], ['"Titre"'], ["R2"]),
         ["Q1", "Q2", "exit"])
    before = stored(tmp_path)
    capsys.readouterr()
    client = FakeClient()
    chat(monkeypatch, tmp_path, client, ["/history", "/history x", "exit"],
         "--session", "k7f2qa")
    output = capsys.readouterr().out
    assert output == ("Chatting with model. Type '/persona' to list profiles or 'exit' to quit.\n"
                      "Session k7f2qa — Titre\n"
                      "1. Q1\n2. Q2\n"
                      "usage: /history\n")
    assert client.requests == []
    assert stored(tmp_path) == before


@pytest.mark.parametrize("text, line", [
    ("Simple", "Simple"),
    ("  Espaces autour  ", "Espaces autour"),
    ("Première\nseconde", "Première …"),
    ("\n\n  Après des lignes vides  \n", "Après des lignes vides"),
    ("Fin\n\n", "Fin"),
    ("y" * 100, "y" * 100),
    ("y" * 101, "y" * 100 + " …"),
    ("y" * 150 + "\nsuite", "y" * 100 + " …"),
])
def test_each_message_is_cut_to_one_line(text, line):
    assert cli._history([Message(role="user", content=text)]) == f"1. {line}"


def test_numbering_counts_only_listed_messages():
    messages = [Message(role="user", content=f"Q{i}") for i in range(1, 12)]
    messages.insert(3, Message(role="user", content="Tool result from t:\n{}"))
    lines = cli._history(messages).split("\n")
    assert lines[0] == "1. Q1" and lines[3] == "4. Q4" and lines[-1] == "11. Q11"
