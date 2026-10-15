"""T29 tester: adversarial checks of persistent CLI sessions through cli.main."""

import json
import os
import sqlite3
from itertools import count

import pytest

from fakes import FakeClient
from sensai.app import cli, conversations
from sensai.app.personas import PersonaRegistry
from sensai.app.settings import Settings
from sensai.core.cancellation import OperationCancelled
from sensai.core.contracts import Profile
from sensai.core.errors import LLMError
from sensai.memory import storage
from sensai.memory.storage import StorageError, StorageRepository

PROFILE_HEADER = "Profil de la créatrice (instructions personnalisées) :"


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    for name in list(os.environ):
        if name.startswith("SENSAI_") or name == "OLLAMA_HOST":
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(cli, "Settings", lambda: Settings(_env_file=None))
    monkeypatch.setattr(cli, "DEFAULT_DB_PATH", str(tmp_path / "default.sqlite3"))
    (tmp_path / "prompt.txt").write_text("Shared rules", encoding="utf-8")
    ticks = count(1)
    monkeypatch.setattr(storage, "_now", lambda: f"2026-10-14T15:{next(ticks):02d}:00+00:00")


@pytest.fixture
def ids(monkeypatch):
    queue = []
    monkeypatch.setattr(conversations, "new_session_id", lambda exists: queue.pop(0))
    return queue


def base_argv(tmp_path):
    return ["--prompt", str(tmp_path / "prompt.txt"), "--db", str(tmp_path / "s.db")]


def chat(monkeypatch, tmp_path, client, inputs, *argv, on_read=lambda: None):
    monkeypatch.setattr(cli, "create_client", lambda settings: client)

    class Terminal:
        def __enter__(self):
            self.inputs = iter(inputs)
            return self

        def __exit__(self, *args):
            pass

        def read(self, prompt):
            on_read()
            value = next(self.inputs)
            if isinstance(value, BaseException):
                raise value
            return value

        def cancel_requested(self):
            return False

    monkeypatch.setattr(cli, "TerminalInput", Terminal)
    cli.main(["model", *base_argv(tmp_path), *argv])


def stored(tmp_path, creator="default"):
    with StorageRepository(tmp_path / "s.db") as repository:
        bound = repository.for_creator(creator)
        summaries = bound.sessions.list()
        return summaries, {s.id: bound.sessions.load(s.id) for s in summaries}, \
            bound.profiles.load("default")


def raw_rows(tmp_path):
    connection = sqlite3.connect(tmp_path / "s.db")
    try:
        sessions = connection.execute(
            "SELECT creator_id, session_id, messages, persona_id FROM sessions").fetchall()
        meta = connection.execute(
            "SELECT creator_id, session_id, title FROM session_meta").fetchall()
    finally:
        connection.close()
    return sessions, meta


def write_profile(tmp_path, data, name="profil.json"):
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def no_client(monkeypatch):
    monkeypatch.setattr(cli, "create_client", lambda settings: pytest.fail("client created"))


def persona_prompt(persona_id):
    return PersonaRegistry.from_file(None).get(persona_id).system_prompt


def contents(snapshot):
    return [(m.role, m.content) for m in snapshot.messages]


# --- Session creation timing -------------------------------------------------------------

@pytest.mark.parametrize("inputs", [
    ["exit"],
    [EOFError()],
    ["", "   ", "\t", "exit"],
    ["/persona analyse", "/persona", "/persona nope", "exit"],
    [KeyboardInterrupt(), "quit"],
], ids=["exit", "eof", "empty", "persona-only", "ctrl-c-at-prompt"])
def test_tester_no_session_row_without_a_completed_turn(monkeypatch, tmp_path, capsys, ids, inputs):
    ids.append("k7f2qa")
    client = FakeClient()
    chat(monkeypatch, tmp_path, client, inputs)
    assert "Session k7f2qa\n" in capsys.readouterr().out
    assert raw_rows(tmp_path) == ([], [])
    assert client.requests == []


def test_tester_cancelled_and_errored_first_turns_save_nothing_then_first_success_saves(
    monkeypatch, tmp_path, ids, real_titles
):
    ids.append("k7f2qa")
    client = FakeClient(["part", OperationCancelled("operation cancelled")], [LLMError("down")],
                        ["A1"], ["Titre généré"], ["A2"], ["A3"])
    seen = []
    chat(monkeypatch, tmp_path, client, ["Q0", "Qerr", "Q1", "Q2", "Q3", "exit"],
         on_read=lambda: seen.append(raw_rows(tmp_path)))
    assert seen[:3] == [([], []), ([], []), ([], [])]
    # Title requested exactly once, right after the first completed turn.
    title_calls = [r for r in client.requests if r[1][0].content == conversations.TITLE_PROMPT]
    assert len(title_calls) == 1 and client.requests.index(title_calls[0]) == 3
    # Title request carries only the first exchange, never the failed turns.
    assert [m.content for m in title_calls[0][1]][1] == "Message : Q1\n\nRéponse : A1"
    # Later requests never contain the title prompt nor title answer.
    for _, messages in client.requests[4:]:
        assert conversations.TITLE_PROMPT not in [m.content for m in messages]
        assert "Titre généré" not in [m.content for m in messages]
    assert [m.content for m in client.requests[5][1]] == [
        "Shared rules", "Q1", "A1", "Q2", "A2", "Q3"]
    summaries, sessions, _ = stored(tmp_path)
    assert [(s.id, s.title) for s in summaries] == [("k7f2qa", "Titre généré")]
    assert contents(sessions["k7f2qa"]) == [
        ("user", "Q1"), ("assistant", "A1"), ("user", "Q2"), ("assistant", "A2"),
        ("user", "Q3"), ("assistant", "A3")]


def test_tester_title_after_failed_first_save_uses_only_first_exchange(
    monkeypatch, tmp_path, ids, real_titles, capsys
):
    ids.append("k7f2qa")
    original = storage._SessionStore.save
    failures = [StorageError("disk full")]

    def save(self, snapshot):
        if failures:
            raise failures.pop()
        original(self, snapshot)

    monkeypatch.setattr(storage._SessionStore, "save", save)
    client = FakeClient(["A1"], ["A2"], ["Bon titre"])
    chat(monkeypatch, tmp_path, client, ["Q1", "Q2", "exit"])
    assert "error: session not saved: disk full" in capsys.readouterr().out
    title_request = client.requests[2][1]
    assert title_request[0].content == conversations.TITLE_PROMPT
    assert [m.content for m in title_request][1] == "Message : Q1\n\nRéponse : A1"
    assert stored(tmp_path)[0][0].title == "Bon titre"


# --- Resume across real restarts ---------------------------------------------------------

def test_tester_three_restarts_rebuild_system_and_keep_full_history(
    monkeypatch, tmp_path, capsys, ids, real_titles
):
    ids.append("k7f2qa")
    profile = write_profile(tmp_path, {"ton": "direct"})
    chat(monkeypatch, tmp_path, FakeClient(["A1"], ["Titre"]), ["Q1", "/persona analyse", "exit"],
         "--profile-file", profile)
    capsys.readouterr()
    sessions_rows, _ = raw_rows(tmp_path)
    assert all(m["role"] != "system" for m in json.loads(sessions_rows[0][2]))
    assert sessions_rows[0][3] == "analyse"

    # Second run: resumed persona is the switched one; profile from storage; errored turn dropped.
    client = FakeClient([LLMError("down")], ["A2"])
    chat(monkeypatch, tmp_path, client, ["Qerr", "Q2", "/persona redaction", "exit"],
         "--session", "k7f2qa")
    assert "Session k7f2qa — Titre\n" in capsys.readouterr().out
    profile_text = f"{PROFILE_HEADER}\n- ton : direct"
    system = f"Shared rules\n\n{profile_text}\n\n{persona_prompt('analyse')}"
    assert [m.content for m in client.requests[0][1]] == [system, "Q1", "A1", "Qerr"]
    assert [m.content for m in client.requests[1][1]] == [system, "Q1", "A1", "Q2"]
    assert len(client.requests) == 2  # titled session: no further title call

    # Third run with a new profile: profile replaced, removed key gone, persona redaction restored.
    client = FakeClient(["A3"])
    chat(monkeypatch, tmp_path, client, ["Q3", "exit"], "--session", "k7f2qa",
         "--profile-file", write_profile(tmp_path, {"langue": "fr"}, "p2.json"))
    system = (f"Shared rules\n\n{PROFILE_HEADER}\n- langue : fr\n\n"
              f"{persona_prompt('redaction')}")
    assert [m.content for m in client.requests[0][1]] == [
        system, "Q1", "A1", "Q2", "A2", "Q3"]
    assert [m.role for m in client.requests[0][1]] == [
        "system", "user", "assistant", "user", "assistant", "user"]
    _, sessions, stored_profile = stored(tmp_path)
    assert stored_profile == Profile("default", {"langue": "fr"})
    assert sessions["k7f2qa"].persona_id == "redaction"
    assert [m for _, m in contents(sessions["k7f2qa"])] == ["Q1", "A1", "Q2", "A2", "Q3", "A3"]


def test_tester_resume_with_cleared_profile_drops_profile_block(monkeypatch, tmp_path, ids):
    ids.append("k7f2qa")
    chat(monkeypatch, tmp_path, FakeClient(["A1"]), ["Q1", "exit"],
         "--profile-file", write_profile(tmp_path, {"ton": "direct"}))
    client = FakeClient(["A2"])
    chat(monkeypatch, tmp_path, client, ["Q2", "exit"], "--session", "k7f2qa",
         "--profile-file", write_profile(tmp_path, {}, "empty.json"))
    assert client.requests[0][1][0].content == "Shared rules"
    assert stored(tmp_path)[2] == Profile("default", {})


def test_tester_new_launch_creates_distinct_session_and_keeps_old_one(
    monkeypatch, tmp_path, ids, capsys
):
    ids.extend(["aaaaaa", "bbbbbb"])
    chat(monkeypatch, tmp_path, FakeClient(["A1"]), ["First", "exit"])
    client = FakeClient(["A2"])
    chat(monkeypatch, tmp_path, client, ["Second", "exit"])
    assert [m.content for m in client.requests[0][1]] == ["Shared rules", "Second"]
    summaries, sessions, _ = stored(tmp_path)
    assert [s.id for s in summaries] == ["bbbbbb", "aaaaaa"]
    assert [m for _, m in contents(sessions["aaaaaa"])] == ["First", "A1"]
    capsys.readouterr()
    cli.main(["--list-sessions", "--db", str(tmp_path / "s.db")])
    assert [line.split("  ")[0] for line in capsys.readouterr().out.splitlines()] == [
        "bbbbbb", "aaaaaa"]


def test_tester_new_session_id_avoids_existing_ids(monkeypatch, tmp_path):
    letters = iter("aaaaaa" + "aaaaaa" + "bbbbbb")
    alphabets = set()

    def choice(alphabet):
        alphabets.add(alphabet)
        return next(letters)

    monkeypatch.setattr(conversations.secrets, "choice", choice)
    chat(monkeypatch, tmp_path, FakeClient(["A1"]), ["First", "exit"])
    chat(monkeypatch, tmp_path, FakeClient(["A2"]), ["Second", "exit"])
    assert sorted(s.id for s in stored(tmp_path)[0]) == ["aaaaaa", "bbbbbb"]
    assert alphabets == {conversations.ID_ALPHABET}


def test_tester_environment_persona_applies_to_new_sessions(monkeypatch, tmp_path, ids):
    ids.append("k7f2qa")
    monkeypatch.setenv("SENSAI_PERSONA", "analyse")
    client = FakeClient(["A1"])
    chat(monkeypatch, tmp_path, client, ["Q1", "exit"])
    assert client.requests[0][1][0].content == f"Shared rules\n\n{persona_prompt('analyse')}"
    assert stored(tmp_path)[1]["k7f2qa"].persona_id == "analyse"


def test_tester_persona_switch_before_first_turn_is_saved_with_first_turn(
    monkeypatch, tmp_path, ids
):
    ids.append("k7f2qa")
    chat(monkeypatch, tmp_path, FakeClient(["A1"]), ["/persona analyse", "Q1", "exit"],
         "--persona", "redaction")
    assert stored(tmp_path)[1]["k7f2qa"].persona_id == "analyse"


def test_tester_resumed_untitled_session_gets_title_once_from_first_stored_exchange(
    monkeypatch, tmp_path, ids, real_titles
):
    ids.append("k7f2qa")
    chat(monkeypatch, tmp_path, FakeClient(["A1"], [""]), ["Q1", "exit"])  # invalid title reply
    connection = sqlite3.connect(tmp_path / "s.db")
    connection.execute("UPDATE session_meta SET title = NULL")
    connection.commit()
    connection.close()
    client = FakeClient(["A2"], ["Reprise titrée"], ["A3"])
    chat(monkeypatch, tmp_path, client, ["Q2", "Q3", "exit"], "--session", "k7f2qa")
    assert [m.content for m in client.requests[1][1]][1] == "Message : Q1\n\nRéponse : A1"
    assert len(client.requests) == 3
    assert stored(tmp_path)[0][0].title == "Reprise titrée"


# --- Profile handling --------------------------------------------------------------------

@pytest.mark.parametrize("argv,message", [
    (["--session", "zzzzzz"], "unknown session"),
    (["--session", "k7f2qa", "--personas-file", "CATALOGUE"], "no longer available"),
])
def test_tester_profile_not_written_when_session_resolution_fails(
    monkeypatch, tmp_path, ids, argv, message
):
    ids.append("k7f2qa")
    catalogue = tmp_path / "personas.json"
    catalogue.write_text(json.dumps([{
        "id": "editor", "name": "Édition", "tone": "Direct", "role": "Revise",
        "response_scope": "Captions"}]), encoding="utf-8")
    chat(monkeypatch, tmp_path, FakeClient(["A1"]), ["Q1", "exit"],
         "--profile-file", write_profile(tmp_path, {"ton": "direct"}),
         "--persona", "analyse")
    argv = [str(catalogue) if a == "CATALOGUE" else a for a in argv]
    no_client(monkeypatch)
    with pytest.raises(SystemExit, match=message):
        cli.main(["model", *base_argv(tmp_path), *argv,
                  "--profile-file", write_profile(tmp_path, {"autre": "x"}, "p2.json")])
    assert stored(tmp_path)[2] == Profile("default", {"ton": "direct"})


def test_tester_profile_block_keeps_stored_key_order(monkeypatch, tmp_path, ids):
    ids.extend(["aaaaaa", "bbbbbb"])
    client = FakeClient(["A1"])
    chat(monkeypatch, tmp_path, client, ["Q1", "exit"],
         "--profile-file", write_profile(tmp_path, {"zeta": "1", "alpha": "2"}))
    client = FakeClient(["A2"])
    chat(monkeypatch, tmp_path, client, ["Q2", "exit"])
    assert client.requests[0][1][0].content == (
        f"Shared rules\n\n{PROFILE_HEADER}\n- zeta : 1\n- alpha : 2")


def test_tester_profile_is_creator_scoped(monkeypatch, tmp_path, ids):
    ids.extend(["aaaaaa", "bbbbbb"])
    chat(monkeypatch, tmp_path, FakeClient(["A"]), ["Q", "exit"], "--creator", "alice",
         "--profile-file", write_profile(tmp_path, {"ton": "alice"}))
    client = FakeClient(["A"])
    chat(monkeypatch, tmp_path, client, ["Q", "exit"], "--creator", "bob")
    assert client.requests[0][1][0].content == "Shared rules"


# --- Isolation and early errors ----------------------------------------------------------

def test_tester_same_id_two_creators_titles_and_deletes_are_isolated(monkeypatch, tmp_path, ids):
    ids.extend(["aaaaaa", "aaaaaa"])
    chat(monkeypatch, tmp_path, FakeClient(["A"]), ["Alice q", "exit"], "--creator", "alice")
    chat(monkeypatch, tmp_path, FakeClient(["B"]), ["Bob q", "exit"], "--creator", "bob")
    with StorageRepository(tmp_path / "s.db") as repository:
        alice = repository.for_creator("alice").sessions
        bob = repository.for_creator("bob").sessions
        assert [s.title for s in alice.list()] == ["Alice q"]
        assert [s.title for s in bob.list()] == ["Bob q"]
        alice.set_title("aaaaaa", "Nouveau")
        assert [s.title for s in bob.list()] == ["Bob q"]
        alice.delete("aaaaaa")
        assert alice.list() == () and [s.id for s in bob.list()] == ["aaaaaa"]
    client = FakeClient(["B2"])
    chat(monkeypatch, tmp_path, client, ["Bob 2", "exit"], "--creator", "bob",
         "--session", "aaaaaa")
    assert [m.content for m in client.requests[0][1]][1:] == ["Bob q", "B", "Bob 2"]


@pytest.mark.parametrize("argv,message", [
    (["--session", "a\x1bb"], "^error: invalid session id$"),
    (["--session", "a\x7fb"], "^error: invalid session id$"),
    (["--session", "x" * 256], "^error: invalid session id$"),
    (["--session", ""], "^error: invalid session id$"),
    (["--creator", "\t"], "^error: invalid creator id$"),
    (["--creator", "a\nb"], "^error: invalid creator id$"),
    (["--creator", "x" * 256], "^error: invalid creator id$"),
])
def test_tester_invalid_ids_fail_before_client(monkeypatch, tmp_path, argv, message):
    no_client(monkeypatch)
    with pytest.raises(SystemExit, match=message):
        cli.main(["model", *base_argv(tmp_path), *argv])


def test_tester_corrupt_stored_session_fails_before_client(monkeypatch, tmp_path, ids):
    ids.append("k7f2qa")
    chat(monkeypatch, tmp_path, FakeClient(["A"]), ["Q", "exit"])
    connection = sqlite3.connect(tmp_path / "s.db")
    connection.execute("UPDATE sessions SET messages = '{not json'")
    connection.commit()
    connection.close()
    no_client(monkeypatch)
    with pytest.raises(SystemExit, match="^error: invalid stored session messages$"):
        cli.main(["model", *base_argv(tmp_path), "--session", "k7f2qa"])


def test_tester_unknown_saved_persona_error_is_before_client_with_custom_catalogue(
    monkeypatch, tmp_path, ids
):
    ids.append("k7f2qa")
    chat(monkeypatch, tmp_path, FakeClient(["A"]), ["Q", "exit"], "--persona", "analyse")
    connection = sqlite3.connect(tmp_path / "s.db")
    connection.execute("UPDATE sessions SET persona_id = 'gone'")
    connection.commit()
    connection.close()
    no_client(monkeypatch)
    with pytest.raises(SystemExit, match="^error: persona 'gone' saved with session k7f2qa "):
        cli.main(["model", *base_argv(tmp_path), "--session", "k7f2qa"])


def test_tester_list_personas_does_not_touch_storage(monkeypatch, tmp_path, capsys):
    no_client(monkeypatch)
    cli.main(["--list-personas", "--db", str(tmp_path / "s.db")])
    assert "analyse" in capsys.readouterr().out
    assert not (tmp_path / "s.db").exists()


def test_tester_list_sessions_on_missing_database_creates_no_file(monkeypatch, tmp_path, capsys):
    no_client(monkeypatch)
    cli.main(["--list-sessions", "--db", str(tmp_path / "missing.db")])
    assert capsys.readouterr().out == ""
    assert not (tmp_path / "missing.db").exists()


def test_tester_list_dates_are_utc_last_update(monkeypatch, tmp_path, capsys, ids):
    ids.append("k7f2qa")
    chat(monkeypatch, tmp_path, FakeClient(["A1"], ["A2"]), ["Q1", "Q2", "exit"])
    connection = sqlite3.connect(tmp_path / "s.db")
    connection.execute("UPDATE session_meta SET created_at = '2026-01-01T00:00:00+00:00', "
                       "updated_at = '2026-10-14T17:30:00+02:00'")
    connection.commit()
    connection.close()
    capsys.readouterr()
    cli.main(["--list-sessions", "--db", str(tmp_path / "s.db")])
    assert capsys.readouterr().out == "k7f2qa  2026-10-14 15:30  Q1\n"


# --- Write failures ----------------------------------------------------------------------

def test_tester_meta_failure_rolls_back_whole_turn_and_chat_continues(
    monkeypatch, tmp_path, capsys, ids
):
    ids.append("k7f2qa")
    ticks = count(1)

    def now():
        tick = next(ticks)
        if tick == 2:  # call 1 is the fresh-database migration, call 2 the first save
            raise sqlite3.OperationalError("disk I/O error")
        return f"2026-10-14T15:{tick:02d}:00+00:00"

    monkeypatch.setattr(storage, "_now", now)
    seen = []
    client = FakeClient(["A1"], ["A2"])
    chat(monkeypatch, tmp_path, client, ["Q1", "Q2", "exit"],
         on_read=lambda: seen.append(raw_rows(tmp_path)))
    out = capsys.readouterr().out
    assert "error: session not saved:" in out and "disk I/O error" in out
    assert seen[1] == ([], [])  # the sessions upsert was rolled back with the meta insert
    _, sessions, _ = stored(tmp_path)
    assert [m for _, m in contents(sessions["k7f2qa"])] == ["Q1", "A1", "Q2", "A2"]


def test_tester_persona_switch_save_failure_is_reported_and_chat_continues(
    monkeypatch, tmp_path, capsys, ids
):
    ids.append("k7f2qa")
    original = storage._SessionStore.save
    calls = count()

    def save(self, snapshot):
        if next(calls) == 1:
            raise StorageError("locked")
        original(self, snapshot)

    monkeypatch.setattr(storage._SessionStore, "save", save)
    client = FakeClient(["A1"], ["A2"])
    chat(monkeypatch, tmp_path, client, ["Q1", "/persona analyse", "Q2", "exit"])
    assert "error: session not saved: locked" in capsys.readouterr().out
    _, sessions, _ = stored(tmp_path)
    assert sessions["k7f2qa"].persona_id == "analyse"
    assert [m for _, m in contents(sessions["k7f2qa"])] == ["Q1", "A1", "Q2", "A2"]


def test_tester_title_save_failure_is_reported_without_stopping_chat(
    monkeypatch, tmp_path, capsys, ids
):
    ids.append("k7f2qa")
    original = storage._SessionStore.set_title
    failures = [StorageError("busy")]

    def set_title(self, session_id, title):
        if failures:
            raise failures.pop()
        original(self, session_id, title)

    monkeypatch.setattr(storage._SessionStore, "set_title", set_title)
    chat(monkeypatch, tmp_path, FakeClient(["A1"], ["A2"]), ["Q1", "Q2", "exit"])
    assert "error: session title not saved: busy" in capsys.readouterr().out
    summaries, sessions, _ = stored(tmp_path)
    assert summaries[0].title == "Q1"
    assert len(sessions["k7f2qa"].messages) == 4
