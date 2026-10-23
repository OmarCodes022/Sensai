"""The /history REPL command: shows the conversation without contacting the model or saving."""

import io

import pytest

from fakes import FakeClient, FakeSessionStore, scripted_terminal
from sensai.chat import saved_sessions
from sensai.chat.personas import PersonaRegistry
from sensai.chat.saved_sessions import SessionRecorder
from sensai.chat.session import ChatSession
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


def test_two_exchanges_in_order_without_system_prompt_and_multiline_as_is():
    client = FakeClient(["Bonjour", " !"], ["Ligne 1\nLigne 2"])
    session = ChatSession(client, "model", "secret system")
    output = run(session, ["Salut", "Deux\nlignes", "/history", "exit"])
    assert output.endswith(
        "Vous : Salut\n\nSensai : Bonjour !\n\n"
        "Vous : Deux\nlignes\n\nSensai : Ligne 1\nLigne 2\n")
    assert "secret system" not in output


def test_persona_switch_system_prompt_is_not_shown():
    session = ChatSession(FakeClient(["R1"]), "model", "Base rules")
    output = run(session, ["/persona analyse", "Q1", "/history", "exit"],
                 persona_registry=PersonaRegistry.from_file(None), base_prompt="Base rules")
    history = output.split("Persona sélectionnée : analyse\n", 1)[1].split("R1\n", 1)[1]
    assert history == "Vous : Q1\n\nSensai : R1\n"
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
    assert [m.content for m in messages] == ["sys", "Q1", "R1"]
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
                      "Vous : Q1\n\nSensai : R1\n\nVous : Q2\n\nSensai : R2\n"
                      "usage: /history\n")
    assert client.requests == []
    assert stored(tmp_path) == before
