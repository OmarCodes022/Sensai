"""T29 persistent CLI sessions through cli.main, with scripted clients and tmp SQLite."""

import json
import os
import re
import sqlite3
from itertools import count
from pathlib import Path
from time import monotonic

import pytest

from fakes import FakeClient
from sensai.app import cli, conversations
from sensai.app.personas import PersonaRegistry
from sensai.app.settings import Settings
from sensai.core.cancellation import OperationCancelled, OperationTimedOut
from sensai.core.contracts import Profile, SessionSnapshot
from sensai.core.errors import LLMError
from sensai.core.messages import Message
from sensai.memory import storage
from sensai.memory.storage import StorageError, StorageRepository

ROOT = Path(__file__).resolve().parents[3]
PROFILE = "Profil de la créatrice (instructions personnalisées) :\n- ton : direct\n- public : mode"
EDITOR = {"id": "editor", "name": "Édition", "tone": "Direct", "role": "Revise drafts",
          "response_scope": "Caption revisions"}


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


def chat(monkeypatch, tmp_path, client, inputs, *argv, on_read=lambda: None, model=("model",)):
    monkeypatch.setattr(cli, "create_client", lambda settings: client)

    class Terminal:
        def __enter__(self):
            self.inputs = iter(inputs)
            return self

        def __exit__(self, *args):
            pass

        def read(self, prompt):
            on_read()
            return next(self.inputs)

        def cancel_requested(self):
            return False

    monkeypatch.setattr(cli, "TerminalInput", Terminal)
    cli.main([*model, "--prompt", str(tmp_path / "prompt.txt"), "--db", str(tmp_path / "s.db"),
              *argv])


def stored(tmp_path, creator="default"):
    with StorageRepository(tmp_path / "s.db") as repository:
        bound = repository.for_creator(creator)
        summaries = bound.sessions.list()
        return summaries, {s.id: bound.sessions.load(s.id) for s in summaries}, \
            bound.profiles.load("default")


def write_profile(tmp_path, data, name="profil.json"):
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def no_client(monkeypatch):
    monkeypatch.setattr(cli, "create_client", lambda settings: pytest.fail("client created"))


def persona_prompt(persona_id, path=None):
    return PersonaRegistry.from_file(path).get(persona_id).system_prompt


def test_t29_new_session_saved_only_after_first_complete_turn_with_separate_title(
    monkeypatch, tmp_path, capsys, real_titles
):
    client = FakeClient([LLMError("down")], ["partial", OperationCancelled("operation cancelled")],
                        ["late", OperationTimedOut("operation timed out")],
                        ["Bonjour", " !"], ['"Salutations matinales"'], ["Encore"])
    snapshots = []
    chat(monkeypatch, tmp_path, client,
         ["   ", "Fails", "Interrupted", "Too slow", "Salut", "Again", "exit"],
         on_read=lambda: snapshots.append(stored(tmp_path)[0]))
    output = capsys.readouterr().out
    session_id = re.search(r"^Session (\S+)$", output, re.M).group(1)
    assert re.fullmatch(f"[{conversations.ID_ALPHABET}]{{6}}", session_id)
    assert output.index("Chatting with model") < output.index(f"Session {session_id}")
    assert snapshots[:5] == [()] * 5
    assert [s.id for s in snapshots[5]] == [session_id]
    summaries, sessions, _ = stored(tmp_path)
    assert [(s.id, s.title) for s in summaries] == [(session_id, "Salutations matinales")]
    assert sessions[session_id] == SessionSnapshot(session_id, (
        Message(role="user", content="Salut"), Message(role="assistant", content="Bonjour !"),
        Message(role="user", content="Again"), Message(role="assistant", content="Encore"),
    ), None)
    title_request = client.requests[4][1]
    assert [m.role for m in title_request] == ["system", "user"]
    assert title_request[0].content == conversations.TITLE_PROMPT
    assert client.calls[5] == ["Shared rules", "Salut", "Bonjour !", "Again"]
    assert len(client.requests) == 6


def test_t29_restart_resumes_shared_profile_persona_then_previous_turns(
    monkeypatch, tmp_path, capsys, ids
):
    ids.append("k7f2qa")
    profile = write_profile(tmp_path, {"ton": "direct", "public": "mode"})
    chat(monkeypatch, tmp_path, FakeClient(["R1"], ["R2"]), ["Premier message", "Second", "exit"],
         "--profile-file", profile, "--persona", "redaction")
    assert "Session k7f2qa\n" in capsys.readouterr().out
    client = FakeClient(["R3"])
    chat(monkeypatch, tmp_path, client, ["Third", "exit"], "--session", "k7f2qa")
    system = "Shared rules\n\n" + PROFILE + "\n\n" + persona_prompt("redaction")
    assert client.calls == [[system, "Premier message", "R1", "Second", "R2", "Third"]]
    assert [m.role for m in client.requests[0][1]] == [
        "system", "user", "assistant", "user", "assistant", "user"]
    assert "Session k7f2qa — Premier message\n" in capsys.readouterr().out
    summaries, sessions, _ = stored(tmp_path)
    assert len(summaries) == 1 and summaries[0].title == "Premier message"
    assert [m.content for m in sessions["k7f2qa"].messages][-2:] == ["Third", "R3"]
    assert sessions["k7f2qa"].persona_id == "redaction"


def test_t29_explicit_persona_wins_and_runtime_switch_is_persisted(
    monkeypatch, tmp_path, capsys, ids
):
    ids.append("k7f2qa")
    chat(monkeypatch, tmp_path, FakeClient(["R1"]), ["Q1", "exit"], "--persona", "redaction")
    client = FakeClient(["R2"], ["R3"])
    personas = []
    chat(monkeypatch, tmp_path, client, ["Q2", "/persona analyse", "Q3", "exit"],
         "--session", "k7f2qa", "--persona", "communaute",
         on_read=lambda: personas.append(stored(tmp_path)[1]["k7f2qa"].persona_id))
    assert client.calls[0][0] == "Shared rules\n\n" + persona_prompt("communaute")
    assert client.calls[1][0] == "Shared rules\n\n" + persona_prompt("analyse")
    assert personas == ["redaction", "communaute", "analyse", "analyse"]
    client = FakeClient(["R4"])
    chat(monkeypatch, tmp_path, client, ["Q4", "exit"], "--session", "k7f2qa")
    assert client.calls[0][:2] == ["Shared rules\n\n" + persona_prompt("analyse"), "Q1"]


def test_t29_environment_persona_does_not_override_saved_persona(monkeypatch, tmp_path, ids):
    ids.append("k7f2qa")
    chat(monkeypatch, tmp_path, FakeClient(["R1"]), ["Q1", "exit"])
    monkeypatch.setenv("SENSAI_PERSONA", "analyse")
    client = FakeClient(["R2"])
    chat(monkeypatch, tmp_path, client, ["Q2", "exit"], "--session", "k7f2qa")
    assert client.calls[0][0] == "Shared rules"


def test_t29_missing_saved_persona_fails_before_client(monkeypatch, tmp_path, ids):
    ids.append("k7f2qa")
    catalogue = tmp_path / "personas.json"
    catalogue.write_text(json.dumps([EDITOR]), encoding="utf-8")
    chat(monkeypatch, tmp_path, FakeClient(["R1"]), ["Q1", "exit"],
         "--personas-file", str(catalogue), "--persona", "editor")
    no_client(monkeypatch)
    with pytest.raises(SystemExit, match="^error: persona 'editor' saved with session k7f2qa "
                                         "is no longer available; pass --persona$"):
        cli.main(["model", "--prompt", str(tmp_path / "prompt.txt"),
                  "--db", str(tmp_path / "s.db"), "--session", "k7f2qa"])
    client = FakeClient(["R2"])
    chat(monkeypatch, tmp_path, client, ["Q2", "exit"], "--session", "k7f2qa", "--persona", "analyse")
    assert client.calls[0][:3] == ["Shared rules\n\n" + persona_prompt("analyse"), "Q1", "R1"]


def test_t29_profile_file_replaces_stored_profile_then_is_injected_without_file(
    monkeypatch, tmp_path
):
    first = write_profile(tmp_path, {"ton": "doux", "langue": "fr"}, "first.json")
    chat(monkeypatch, tmp_path, FakeClient(["R"]), ["Q", "exit"], "--profile-file", first)
    second = write_profile(tmp_path, {"ton": "direct", "public": "mode"}, "second.json")
    client = FakeClient(["R"])
    chat(monkeypatch, tmp_path, client, ["Q", "exit"], "--profile-file", second)
    assert client.calls[0][0] == "Shared rules\n\n" + PROFILE
    assert stored(tmp_path)[2] == Profile("default", {"ton": "direct", "public": "mode"})
    client = FakeClient(["R"], ["R2"])
    chat(monkeypatch, tmp_path, client, ["Q", "/persona analyse", "Q2", "exit"])
    assert client.calls[0][0] == "Shared rules\n\n" + PROFILE
    assert client.calls[1][0] == "Shared rules\n\n" + PROFILE + "\n\n" + persona_prompt("analyse")


@pytest.mark.parametrize("persona_id", [None, "redaction"])
def test_t29_empty_profile_keeps_prompt_identical(monkeypatch, tmp_path, persona_id):
    expected = "Shared rules" + (f"\n\n{persona_prompt(persona_id)}" if persona_id else "")
    persona = ["--persona", persona_id] if persona_id else []
    client = FakeClient(["R"])
    chat(monkeypatch, tmp_path, client, ["Q", "exit"], *persona)
    assert client.calls[0][0] == expected
    chat(monkeypatch, tmp_path, FakeClient(["R"]), ["Q", "exit"],
         "--profile-file", write_profile(tmp_path, {"ton": "direct"}))
    client = FakeClient(["R"])
    chat(monkeypatch, tmp_path, client, ["Q", "exit"], *persona,
         "--profile-file", write_profile(tmp_path, {}, "empty.json"))
    assert client.calls[0][0] == expected
    assert stored(tmp_path)[2] == Profile("default", {})


@pytest.mark.parametrize("contents", [
    b"[]", b'"text"', b'{"": "x"}', b'{"ton": 1}', b'{"ton": "  "}', b"{bad", b"\xff\xfe", None,
])
def test_t29_invalid_profile_file_fails_before_client_and_keeps_stored_profile(
    monkeypatch, tmp_path, contents
):
    chat(monkeypatch, tmp_path, FakeClient(["R"]), ["Q", "exit"],
         "--profile-file", write_profile(tmp_path, {"ton": "direct"}))
    bad = tmp_path / "bad.json"
    if contents is not None:
        bad.write_bytes(contents)
    no_client(monkeypatch)
    with pytest.raises(SystemExit, match="^error: cannot load profile: "):
        cli.main(["model", "--prompt", str(tmp_path / "prompt.txt"),
                  "--db", str(tmp_path / "s.db"), "--profile-file", str(bad)])
    assert stored(tmp_path)[2] == Profile("default", {"ton": "direct"})


def make_database(path, kind):
    if kind == "garbage":
        path.write_bytes(b"this is not a sqlite database" * 100)
    elif kind == "directory":
        path.mkdir()
    elif kind == "future":
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA user_version = 99")
        connection.close()
    elif kind == "foreign":
        connection = sqlite3.connect(path)
        connection.execute("CREATE TABLE other (value TEXT)")
        connection.close()


@pytest.mark.parametrize("kind,match", [
    ("garbage", "not a database"), ("directory", "unable to open"),
    ("future", "unsupported storage version 99"), ("foreign", "unversioned database"),
])
@pytest.mark.parametrize("listing", [False, True], ids=["chat", "list"])
def test_t29_bad_database_fails_before_client(monkeypatch, tmp_path, kind, match, listing):
    make_database(tmp_path / "s.db", kind)
    no_client(monkeypatch)
    argv = ["--list-sessions"] if listing else ["model"]
    with pytest.raises(SystemExit, match=f"^error: cannot open session database: .*{match}"):
        cli.main([*argv, "--db", str(tmp_path / "s.db")])


@pytest.mark.parametrize("argv,message", [
    (["--session", "zzzzzz"], r"^error: unknown session: zzzzzz \(see --list-sessions\)$"),
    (["--session", "bad\nid"], "^error: invalid session id$"),
    (["--session", " "], "^error: invalid session id$"),
    (["--creator", ""], "^error: invalid creator id$"),
    (["--creator", "x" * 256, "--list-sessions"], "^error: invalid creator id$"),
])
def test_t29_unknown_or_invalid_ids_fail_before_client(monkeypatch, tmp_path, argv, message):
    StorageRepository(tmp_path / "s.db").close()  # listing a missing database prints nothing
    no_client(monkeypatch)
    with pytest.raises(SystemExit, match=message):
        cli.main(["model", "--prompt", str(tmp_path / "prompt.txt"),
                  "--db", str(tmp_path / "s.db"), *argv])


def test_t29_sessions_are_scoped_by_creator(monkeypatch, tmp_path, ids):
    ids.extend(["aaaaaa", "aaaaaa"])
    chat(monkeypatch, tmp_path, FakeClient(["R"]), ["Alice", "exit"], "--creator", "alice")
    chat(monkeypatch, tmp_path, FakeClient(["R"]), ["Bob", "exit"], "--creator", "bob")
    assert stored(tmp_path, "alice")[1]["aaaaaa"].messages[0].content == "Alice"
    assert stored(tmp_path, "bob")[1]["aaaaaa"].messages[0].content == "Bob"
    assert stored(tmp_path)[0] == ()
    no_client(monkeypatch)
    with pytest.raises(SystemExit, match="unknown session: aaaaaa"):
        cli.main(["model", "--prompt", str(tmp_path / "prompt.txt"),
                  "--db", str(tmp_path / "s.db"), "--session", "aaaaaa"])


def test_t29_write_failure_is_reported_and_next_save_has_full_history(
    monkeypatch, tmp_path, capsys, ids
):
    ids.append("k7f2qa")
    original = storage._SessionStore.save
    failures = [StorageError("disk full")]

    def save(self, snapshot):
        if failures:
            raise failures.pop()
        original(self, snapshot)

    monkeypatch.setattr(storage._SessionStore, "save", save)
    seen = []
    client = FakeClient(["R1"], ["R2"])
    chat(monkeypatch, tmp_path, client, ["Q1", "Q2", "exit"],
         on_read=lambda: seen.append(stored(tmp_path)[0]))
    output = capsys.readouterr().out
    assert "R1\nerror: session not saved: disk full\n" in output and "R2" in output
    assert seen[:2] == [(), ()]
    summaries, sessions, _ = stored(tmp_path)
    assert [m.content for m in sessions["k7f2qa"].messages] == ["Q1", "R1", "Q2", "R2"]
    assert summaries[0].title == "Q1"
    assert client.calls[1] == ["Shared rules", "Q1", "R1", "Q2"]


@pytest.mark.parametrize("reply", [[""], ["Ligne\nDeux"], ["x" * 61], [LLMError("down")],
                                   ["T", OperationCancelled("operation cancelled")]])
def test_t29_invalid_title_reply_falls_back_to_truncated_first_message(
    monkeypatch, tmp_path, real_titles, reply
):
    question = "Prépare un calendrier éditorial complet pour le mois prochain"
    client = FakeClient(["R1"], reply, ["R2"])
    chat(monkeypatch, tmp_path, client, [question, "Q2", "exit"])
    summaries, sessions, _ = stored(tmp_path)
    assert summaries[0].title == question[:39] + "…"
    assert client.calls[2] == ["Shared rules", question, "R1", "Q2"]
    assert [m.content for m in sessions[summaries[0].id].messages] == [question, "R1", "Q2", "R2"]


def test_t29_list_sessions_needs_no_model_or_client_and_is_sorted(monkeypatch, tmp_path, capsys, ids):
    ids.extend(["aaaaaa", "bbbbbb"])
    chat(monkeypatch, tmp_path, FakeClient(["R"]), ["Première  session\nsuite", "exit"])
    chat(monkeypatch, tmp_path, FakeClient(["R"]), ["Deuxième", "exit"])
    with StorageRepository(tmp_path / "s.db") as repository:
        repository.for_creator("default").sessions.set_title("bbbbbb", "Titre lisible")
    connection = sqlite3.connect(tmp_path / "s.db")
    connection.execute("UPDATE session_meta SET title = NULL WHERE session_id = 'aaaaaa'")
    connection.commit()
    connection.close()
    capsys.readouterr()
    no_client(monkeypatch)
    monkeypatch.setattr(cli, "load_system_prompt", lambda path: pytest.fail("prompt read"))
    cli.main(["--list-sessions", "--db", str(tmp_path / "s.db")])
    assert capsys.readouterr().out.splitlines() == [
        "bbbbbb  2026-10-14 15:03  Titre lisible",
        "aaaaaa  2026-10-14 15:02  Première session",
    ]
    cli.main(["--list-sessions", "--db", str(tmp_path / "s.db"), "--creator", "nobody"])
    assert capsys.readouterr().out == ""


def test_t29_cli_options_override_environment(monkeypatch, tmp_path, capsys, ids):
    monkeypatch.setenv("SENSAI_DB", str(tmp_path / "env.db"))
    monkeypatch.setenv("SENSAI_CREATOR", "env-creator")
    monkeypatch.setenv("SENSAI_PROFILE_FILE", str(tmp_path / "env-profile.json"))
    settings = Settings(_env_file=None)
    env_args = cli.parse_args(settings, ["--list-sessions"])
    assert (env_args.db, env_args.creator, env_args.profile_file) == (
        str(tmp_path / "env.db"), "env-creator", str(tmp_path / "env-profile.json"))
    cli_args = cli.parse_args(settings, ["--list-sessions", "--db", "cli.db", "--creator", "cli",
                                         "--profile-file", "cli.json", "--session", "k7f2qa"])
    assert (cli_args.db, cli_args.creator, cli_args.profile_file, cli_args.session) == (
        "cli.db", "cli", "cli.json", "k7f2qa")
    for name in ("SENSAI_DB", "SENSAI_CREATOR", "SENSAI_PROFILE_FILE"):
        monkeypatch.delenv(name)
    defaults = cli.parse_args(Settings(_env_file=None), ["model"])
    assert (defaults.db, defaults.creator, defaults.profile_file, defaults.session) == (
        None, "default", None, None)
    with pytest.raises(SystemExit):
        cli.parse_args(Settings(_env_file=None), [])
    ids.append("k7f2qa")
    monkeypatch.setenv("SENSAI_DB", str(tmp_path / "env.db"))
    monkeypatch.setenv("SENSAI_CREATOR", "env-creator")
    chat(monkeypatch, tmp_path, FakeClient(["R"]), ["Q", "exit"], "--creator", "cli")
    assert [s.id for s in stored(tmp_path, "cli")[0]] == ["k7f2qa"]
    assert not (tmp_path / "env.db").exists()


def test_t29_default_database_stays_out_of_the_repository(monkeypatch, tmp_path, ids):
    ids.append("k7f2qa")
    chat(monkeypatch, tmp_path, FakeClient(["R"]), ["Q", "exit"], "--db", "")
    with StorageRepository(cli.DEFAULT_DB_PATH) as repository:
        assert [s.id for s in repository.for_creator("default").sessions.list()] == ["k7f2qa"]
    assert not (ROOT / "sensai.sqlite3").exists()
    ignored = (ROOT / ".gitignore").read_text().splitlines()
    assert "sensai.sqlite3*" in ignored and "*.local.json" in ignored


def test_t29_real_default_database_path_is_relative_to_cwd(real_default_db_path):
    assert real_default_db_path == "sensai.sqlite3"
    assert cli.DEFAULT_DB_PATH != real_default_db_path


def test_t29_invalid_environment_persona_is_ignored_on_resume(monkeypatch, tmp_path, ids):
    ids.append("k7f2qa")
    chat(monkeypatch, tmp_path, FakeClient(["R1"]), ["Q1", "exit"], "--persona", "analyse")
    monkeypatch.setenv("SENSAI_PERSONA", "ghost")
    client = FakeClient(["R2"])
    chat(monkeypatch, tmp_path, client, ["Q2", "exit"], "--session", "k7f2qa")
    assert client.calls[0][:2] == ["Shared rules\n\n" + persona_prompt("analyse"), "Q1"]
    no_client(monkeypatch)
    with pytest.raises(SystemExit, match="^error: unknown persona: ghost$"):
        cli.main(["model", "--prompt", str(tmp_path / "prompt.txt"),
                  "--db", str(tmp_path / "s.db")])
    with pytest.raises(SystemExit, match="^error: unknown persona: nope$"):
        cli.main(["model", "--prompt", str(tmp_path / "prompt.txt"),
                  "--db", str(tmp_path / "s.db"), "--session", "k7f2qa", "--persona", "nope"])


def test_t29_list_sessions_marks_an_unreadable_session(monkeypatch, tmp_path, capsys, ids):
    ids.extend(["aaaaaa", "bbbbbb"])
    chat(monkeypatch, tmp_path, FakeClient(["R"]), ["Lisible", "exit"])
    chat(monkeypatch, tmp_path, FakeClient(["R"]), ["Cassée", "exit"])
    connection = sqlite3.connect(tmp_path / "s.db")
    connection.execute("UPDATE sessions SET messages = '{not json' WHERE session_id = 'bbbbbb'")
    connection.execute("UPDATE session_meta SET title = NULL")
    connection.commit()
    connection.close()
    capsys.readouterr()
    no_client(monkeypatch)
    cli.main(["--list-sessions", "--db", str(tmp_path / "s.db")])
    assert capsys.readouterr().out.splitlines() == [
        "bbbbbb  2026-10-14 15:03  (titre illisible)",
        "aaaaaa  2026-10-14 15:02  Lisible",
    ]


def test_t29_list_sessions_survives_a_malformed_date(monkeypatch, tmp_path, capsys, ids):
    ids.extend(["aaaaaa", "bbbbbb"])
    chat(monkeypatch, tmp_path, FakeClient(["R"]), ["Bonne date", "exit"])
    chat(monkeypatch, tmp_path, FakeClient(["R"]), ["Mauvaise date", "exit"])
    connection = sqlite3.connect(tmp_path / "s.db")
    connection.execute("UPDATE session_meta SET updated_at = 'pas une date' "
                       "WHERE session_id = 'bbbbbb'")
    connection.commit()
    connection.close()
    capsys.readouterr()
    no_client(monkeypatch)
    cli.main(["--list-sessions", "--db", str(tmp_path / "s.db")])
    assert capsys.readouterr().out.splitlines() == [
        "bbbbbb  ????-??-?? ??:??  Mauvaise date",
        "aaaaaa  2026-10-14 15:02  Bonne date",
    ]


def test_t29_blank_stored_profile_entries_keep_prompt_identical(monkeypatch, tmp_path):
    with StorageRepository(tmp_path / "s.db") as repository:
        repository.for_creator("default").profiles.save(Profile("default", {"ton": " ", " ": "x"}))
    client = FakeClient(["R"])
    chat(monkeypatch, tmp_path, client, ["Q", "exit"])
    assert client.calls[0][0] == "Shared rules"


def test_t29_ctrl_c_during_save_keeps_chatting(monkeypatch, tmp_path, capsys, ids):
    ids.append("k7f2qa")
    original = storage._SessionStore.save
    interrupts = [KeyboardInterrupt()]

    def save(self, snapshot):
        if interrupts:
            raise interrupts.pop()
        original(self, snapshot)

    monkeypatch.setattr(storage._SessionStore, "save", save)
    chat(monkeypatch, tmp_path, FakeClient(["R1"], ["R2"]), ["Q1", "Q2", "exit"])
    assert "R1\nerror: session not saved: interrupted\n" in capsys.readouterr().out
    assert [m.content for m in stored(tmp_path)[1]["k7f2qa"].messages] == ["Q1", "R1", "Q2", "R2"]


@pytest.mark.parametrize("timeout,budget", [("120", 15.0), ("5", 5.0)])
def test_t29_title_request_is_announced_and_has_its_own_deadline(
    monkeypatch, tmp_path, capsys, timeout, budget
):
    remaining = []

    def generate_title(client, model, first_user, first_answer, cancellation):
        remaining.append(cancellation.deadline - monotonic())
        print("<title request>")
        return "Titre"

    monkeypatch.setattr(conversations, "generate_title", generate_title)
    chat(monkeypatch, tmp_path, FakeClient(["R1"], ["R2"]), ["Q1", "Q2", "exit"],
         "--operation-timeout", timeout)
    output = capsys.readouterr().out
    assert "R1\nTitre de la session…\n<title request>\n" in output
    assert output.count("Titre de la session…") == 1
    assert len(remaining) == 1 and budget - 1 < remaining[0] <= budget
    assert stored(tmp_path)[0][0].title == "Titre"
