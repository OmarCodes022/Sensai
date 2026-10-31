"""Persistent CLI sessions and creator profiles through cli.main, with scripted clients and tmp SQLite."""

import json
import re
import sqlite3
from itertools import count
from pathlib import Path
from time import monotonic

import pytest

from fakes import FakeClient, scripted_terminal
from sensai.cli import main as cli
from sensai.chat import saved_sessions
from sensai.chat.personas import PersonaRegistry
from sensai.settings import Settings
from sensai.sandbox import RUN_PYTHON
from sensai.tools import CALCULATE, tool_instructions
from sensai.core.cancellation import OperationCancelled, OperationTimedOut
from sensai.core.ports import Profile, SessionSnapshot
from sensai.core.errors import LLMError
from sensai.core.messages import Message
from sensai.memory import sqlite_store
from sensai.memory.sqlite_store import StorageError, StorageRepository
from sensai.chat.facts import DELETE_FACT, SAVE_FACT
from sensai.chat.questions import ASK_USER

TOOLS = "\n\n" + tool_instructions([CALCULATE, RUN_PYTHON, SAVE_FACT, DELETE_FACT, ASK_USER])

ROOT = Path(__file__).resolve().parents[3]
PROFILE_HEADER = "Profil de la créatrice (instructions personnalisées) :"
PROFILE = "Profil de la créatrice (instructions personnalisées) :\n- ton : direct\n- public : mode"
EDITOR = {"id": "editor", "name": "Édition", "tone": "Direct", "role": "Revise drafts",
          "response_scope": "Caption revisions"}


@pytest.fixture(autouse=True)
def isolated(isolated_settings, monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "DEFAULT_DB_PATH", str(tmp_path / "default.sqlite3"))
    (tmp_path / "prompt.txt").write_text("Shared rules", encoding="utf-8")
    ticks = count(1)
    monkeypatch.setattr(sqlite_store, "_now", lambda: f"2026-10-14T15:{next(ticks):02d}:00+00:00")


@pytest.fixture
def ids(monkeypatch):
    queue = []
    monkeypatch.setattr(saved_sessions, "new_session_id", lambda exists: queue.pop(0))
    return queue


def base_argv(tmp_path):
    return ["--prompt", str(tmp_path / "prompt.txt"), "--db", str(tmp_path / "s.db")]


def chat(monkeypatch, tmp_path, client, inputs, *argv, on_read=lambda: None, model=("model",)):
    monkeypatch.setattr(cli, "create_client", lambda settings: client)
    monkeypatch.setattr(cli, "TerminalInput", scripted_terminal(inputs, on_read))
    cli.main([*model, *base_argv(tmp_path), *argv])


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


def persona_prompt(persona_id, path=None):
    return PersonaRegistry.from_file(path).get(persona_id).system_prompt


def contents(snapshot):
    return [(m.role, m.content) for m in snapshot.messages]


# --- Session lifecycle, profiles and listing ---------------------------------------------

def test_new_session_saved_only_after_first_complete_turn_with_separate_title(
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
    assert re.fullmatch(f"[{saved_sessions.ID_ALPHABET}]{{6}}", session_id)
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
    assert title_request[0].content == saved_sessions.TITLE_PROMPT
    assert client.calls[5] == ["Shared rules" + TOOLS, "Salut", "Bonjour !", "Again"]
    assert len(client.requests) == 6


def test_restart_resumes_shared_profile_persona_then_previous_turns(
    monkeypatch, tmp_path, capsys, ids
):
    ids.append("k7f2qa")
    profile = write_profile(tmp_path, {"ton": "direct", "public": "mode"})
    chat(monkeypatch, tmp_path, FakeClient(["R1"], ["R2"]), ["Premier message", "Second", "exit"],
         "--profile-file", profile, "--persona", "redaction")
    assert "Session k7f2qa\n" in capsys.readouterr().out
    client = FakeClient(["R3"])
    chat(monkeypatch, tmp_path, client, ["Third", "exit"], "--session", "k7f2qa")
    system = "Shared rules\n\n" + PROFILE + "\n\n" + persona_prompt("redaction") + TOOLS
    assert client.calls == [[system, "Premier message", "R1", "Second", "R2", "Third"]]
    assert [m.role for m in client.requests[0][1]] == [
        "system", "user", "assistant", "user", "assistant", "user"]
    assert "Session k7f2qa — Premier message\n" in capsys.readouterr().out
    summaries, sessions, _ = stored(tmp_path)
    assert len(summaries) == 1 and summaries[0].title == "Premier message"
    assert [m.content for m in sessions["k7f2qa"].messages][-2:] == ["Third", "R3"]
    assert sessions["k7f2qa"].persona_id == "redaction"


def test_explicit_persona_wins_and_runtime_switch_is_persisted(
    monkeypatch, tmp_path, capsys, ids
):
    ids.append("k7f2qa")
    chat(monkeypatch, tmp_path, FakeClient(["R1"]), ["Q1", "exit"], "--persona", "redaction")
    client = FakeClient(["R2"], ["R3"])
    personas = []
    chat(monkeypatch, tmp_path, client, ["Q2", "/persona analyse", "Q3", "exit"],
         "--session", "k7f2qa", "--persona", "communaute",
         on_read=lambda: personas.append(stored(tmp_path)[1]["k7f2qa"].persona_id))
    assert client.calls[0][0] == "Shared rules\n\n" + persona_prompt("communaute") + TOOLS
    assert client.calls[1][0] == "Shared rules\n\n" + persona_prompt("analyse") + TOOLS
    assert personas == ["redaction", "communaute", "analyse", "analyse"]
    client = FakeClient(["R4"])
    chat(monkeypatch, tmp_path, client, ["Q4", "exit"], "--session", "k7f2qa")
    assert client.calls[0][:2] == ["Shared rules\n\n" + persona_prompt("analyse") + TOOLS, "Q1"]


def test_environment_persona_does_not_override_saved_persona(monkeypatch, tmp_path, ids):
    ids.append("k7f2qa")
    chat(monkeypatch, tmp_path, FakeClient(["R1"]), ["Q1", "exit"])
    monkeypatch.setenv("SENSAI_PERSONA", "analyse")
    client = FakeClient(["R2"])
    chat(monkeypatch, tmp_path, client, ["Q2", "exit"], "--session", "k7f2qa")
    assert client.calls[0][0] == "Shared rules" + TOOLS


def test_missing_saved_persona_fails_before_client(monkeypatch, tmp_path, ids):
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
    assert client.calls[0][:3] == ["Shared rules\n\n" + persona_prompt("analyse") + TOOLS, "Q1", "R1"]


def test_profile_file_replaces_stored_profile_then_is_injected_without_file(
    monkeypatch, tmp_path
):
    first = write_profile(tmp_path, {"ton": "doux", "langue": "fr"}, "first.json")
    chat(monkeypatch, tmp_path, FakeClient(["R"]), ["Q", "exit"], "--profile-file", first)
    second = write_profile(tmp_path, {"ton": "direct", "public": "mode"}, "second.json")
    client = FakeClient(["R"])
    chat(monkeypatch, tmp_path, client, ["Q", "exit"], "--profile-file", second)
    assert client.calls[0][0] == "Shared rules\n\n" + PROFILE + TOOLS
    assert stored(tmp_path)[2] == Profile("default", {"ton": "direct", "public": "mode"})
    client = FakeClient(["R"], ["R2"])
    chat(monkeypatch, tmp_path, client, ["Q", "/persona analyse", "Q2", "exit"])
    assert client.calls[0][0] == "Shared rules\n\n" + PROFILE + TOOLS
    assert client.calls[1][0] == "Shared rules\n\n" + PROFILE + "\n\n" + persona_prompt("analyse") + TOOLS


@pytest.mark.parametrize("persona_id", [None, "redaction"])
def test_empty_profile_keeps_prompt_identical(monkeypatch, tmp_path, persona_id):
    expected = "Shared rules" + (f"\n\n{persona_prompt(persona_id)}" if persona_id else "") + TOOLS
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
def test_invalid_profile_file_fails_before_client_and_keeps_stored_profile(
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
def test_bad_database_fails_before_client(monkeypatch, tmp_path, kind, match, listing):
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
def test_unknown_or_invalid_ids_fail_before_client(monkeypatch, tmp_path, argv, message):
    StorageRepository(tmp_path / "s.db").close()  # listing a missing database prints nothing
    no_client(monkeypatch)
    with pytest.raises(SystemExit, match=message):
        cli.main(["model", "--prompt", str(tmp_path / "prompt.txt"),
                  "--db", str(tmp_path / "s.db"), *argv])


def test_sessions_are_scoped_by_creator(monkeypatch, tmp_path, ids):
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


def test_write_failure_is_reported_and_next_save_has_full_history(
    monkeypatch, tmp_path, capsys, ids
):
    ids.append("k7f2qa")
    original = sqlite_store._SessionStore.save
    failures = [StorageError("disk full")]

    def save(self, snapshot):
        if failures:
            raise failures.pop()
        original(self, snapshot)

    monkeypatch.setattr(sqlite_store._SessionStore, "save", save)
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
    assert client.calls[1] == ["Shared rules" + TOOLS, "Q1", "R1", "Q2"]


@pytest.mark.parametrize("reply", [[""], ["Ligne\nDeux"], ["x" * 61], [LLMError("down")],
                                   ["T", OperationCancelled("operation cancelled")]])
def test_invalid_title_reply_falls_back_to_truncated_first_message(
    monkeypatch, tmp_path, real_titles, reply
):
    question = "Prépare un calendrier éditorial complet pour le mois prochain"
    client = FakeClient(["R1"], reply, ["R2"])
    chat(monkeypatch, tmp_path, client, [question, "Q2", "exit"])
    summaries, sessions, _ = stored(tmp_path)
    assert summaries[0].title == question[:39] + "…"
    assert client.calls[2] == ["Shared rules" + TOOLS, question, "R1", "Q2"]
    assert [m.content for m in sessions[summaries[0].id].messages] == [question, "R1", "Q2", "R2"]


def test_list_sessions_needs_no_model_or_client_and_is_sorted(monkeypatch, tmp_path, capsys, ids):
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


def test_cli_options_override_environment(monkeypatch, tmp_path, capsys, ids):
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


def test_default_database_stays_out_of_the_repository(monkeypatch, tmp_path, ids):
    ids.append("k7f2qa")
    chat(monkeypatch, tmp_path, FakeClient(["R"]), ["Q", "exit"], "--db", "")
    with StorageRepository(cli.DEFAULT_DB_PATH) as repository:
        assert [s.id for s in repository.for_creator("default").sessions.list()] == ["k7f2qa"]
    assert not (ROOT / "sensai.sqlite3").exists()
    ignored = (ROOT / ".gitignore").read_text().splitlines()
    assert "sensai.sqlite3*" in ignored and "*.local.json" in ignored


def test_real_default_database_path_is_relative_to_cwd(real_default_db_path):
    assert real_default_db_path == "sensai.sqlite3"
    assert cli.DEFAULT_DB_PATH != real_default_db_path


def test_invalid_environment_persona_is_ignored_on_resume(monkeypatch, tmp_path, ids):
    ids.append("k7f2qa")
    chat(monkeypatch, tmp_path, FakeClient(["R1"]), ["Q1", "exit"], "--persona", "analyse")
    monkeypatch.setenv("SENSAI_PERSONA", "ghost")
    client = FakeClient(["R2"])
    chat(monkeypatch, tmp_path, client, ["Q2", "exit"], "--session", "k7f2qa")
    assert client.calls[0][:2] == ["Shared rules\n\n" + persona_prompt("analyse") + TOOLS, "Q1"]
    no_client(monkeypatch)
    with pytest.raises(SystemExit, match="^error: unknown persona: ghost$"):
        cli.main(["model", "--prompt", str(tmp_path / "prompt.txt"),
                  "--db", str(tmp_path / "s.db")])
    with pytest.raises(SystemExit, match="^error: unknown persona: nope$"):
        cli.main(["model", "--prompt", str(tmp_path / "prompt.txt"),
                  "--db", str(tmp_path / "s.db"), "--session", "k7f2qa", "--persona", "nope"])


def test_list_sessions_marks_an_unreadable_session(monkeypatch, tmp_path, capsys, ids):
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


def test_list_sessions_survives_a_malformed_date(monkeypatch, tmp_path, capsys, ids):
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


def test_blank_stored_profile_entries_keep_prompt_identical(monkeypatch, tmp_path):
    with StorageRepository(tmp_path / "s.db") as repository:
        repository.for_creator("default").profiles.save(Profile("default", {"ton": " ", " ": "x"}))
    client = FakeClient(["R"])
    chat(monkeypatch, tmp_path, client, ["Q", "exit"])
    assert client.calls[0][0] == "Shared rules" + TOOLS


def test_ctrl_c_during_save_keeps_chatting(monkeypatch, tmp_path, capsys, ids):
    ids.append("k7f2qa")
    original = sqlite_store._SessionStore.save
    interrupts = [KeyboardInterrupt()]

    def save(self, snapshot):
        if interrupts:
            raise interrupts.pop()
        original(self, snapshot)

    monkeypatch.setattr(sqlite_store._SessionStore, "save", save)
    chat(monkeypatch, tmp_path, FakeClient(["R1"], ["R2"]), ["Q1", "Q2", "exit"])
    assert "R1\nerror: session not saved: interrupted\n" in capsys.readouterr().out
    assert [m.content for m in stored(tmp_path)[1]["k7f2qa"].messages] == ["Q1", "R1", "Q2", "R2"]


@pytest.mark.parametrize("timeout,budget", [("120", 15.0), ("5", 5.0)])
def test_title_request_is_announced_and_has_its_own_deadline(
    monkeypatch, tmp_path, capsys, timeout, budget
):
    remaining = []

    def generate_title(client, model, first_user, first_answer, cancellation):
        remaining.append(cancellation.deadline - monotonic())
        print("<title request>")
        return "Titre"

    monkeypatch.setattr(saved_sessions, "generate_title", generate_title)
    chat(monkeypatch, tmp_path, FakeClient(["R1"], ["R2"]), ["Q1", "Q2", "exit"],
         "--operation-timeout", timeout)
    output = capsys.readouterr().out
    assert "R1\n<title request>\n" in output
    assert "Titre de la session" not in output
    assert len(remaining) == 1 and budget - 1 < remaining[0] <= budget
    assert stored(tmp_path)[0][0].title == "Titre"


# --- Session creation timing -------------------------------------------------------------

@pytest.mark.parametrize("inputs", [
    ["exit"],
    [EOFError()],
    ["", "   ", "\t", "exit"],
    ["/persona analyse", "/persona", "/persona nope", "exit"],
    [KeyboardInterrupt(), "quit"],
], ids=["exit", "eof", "empty", "persona-only", "ctrl-c-at-prompt"])
def test_no_session_row_without_a_completed_turn(monkeypatch, tmp_path, capsys, ids, inputs):
    ids.append("k7f2qa")
    client = FakeClient()
    chat(monkeypatch, tmp_path, client, inputs)
    assert "Session k7f2qa\n" in capsys.readouterr().out
    assert raw_rows(tmp_path) == ([], [])
    assert client.requests == []


def test_cancelled_and_errored_first_turns_save_nothing_then_first_success_saves(
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
    title_calls = [r for r in client.requests if r[1][0].content == saved_sessions.TITLE_PROMPT]
    assert len(title_calls) == 1 and client.requests.index(title_calls[0]) == 3
    # Title request carries only the first exchange, never the failed turns.
    assert [m.content for m in title_calls[0][1]][1] == "Message : Q1\n\nRéponse : A1"
    # Later requests never contain the title prompt nor title answer.
    for _, messages in client.requests[4:]:
        assert saved_sessions.TITLE_PROMPT not in [m.content for m in messages]
        assert "Titre généré" not in [m.content for m in messages]
    assert [m.content for m in client.requests[5][1]] == [
        "Shared rules" + TOOLS, "Q1", "A1", "Q2", "A2", "Q3"]
    summaries, sessions, _ = stored(tmp_path)
    assert [(s.id, s.title) for s in summaries] == [("k7f2qa", "Titre généré")]
    assert contents(sessions["k7f2qa"]) == [
        ("user", "Q1"), ("assistant", "A1"), ("user", "Q2"), ("assistant", "A2"),
        ("user", "Q3"), ("assistant", "A3")]


def test_title_after_failed_first_save_uses_only_first_exchange(
    monkeypatch, tmp_path, ids, real_titles, capsys
):
    ids.append("k7f2qa")
    original = sqlite_store._SessionStore.save
    failures = [StorageError("disk full")]

    def save(self, snapshot):
        if failures:
            raise failures.pop()
        original(self, snapshot)

    monkeypatch.setattr(sqlite_store._SessionStore, "save", save)
    client = FakeClient(["A1"], ["A2"], ["Bon titre"])
    chat(monkeypatch, tmp_path, client, ["Q1", "Q2", "exit"])
    assert "error: session not saved: disk full" in capsys.readouterr().out
    title_request = client.requests[2][1]
    assert title_request[0].content == saved_sessions.TITLE_PROMPT
    assert [m.content for m in title_request][1] == "Message : Q1\n\nRéponse : A1"
    assert stored(tmp_path)[0][0].title == "Bon titre"


# --- Resume across real restarts ---------------------------------------------------------

def test_three_restarts_rebuild_system_and_keep_full_history(
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
    system = f"Shared rules\n\n{profile_text}\n\n{persona_prompt('analyse')}" + TOOLS
    assert [m.content for m in client.requests[0][1]] == [system, "Q1", "A1", "Qerr"]
    assert [m.content for m in client.requests[1][1]] == [system, "Q1", "A1", "Q2"]
    assert len(client.requests) == 2  # titled session: no further title call

    # Third run with a new profile: profile replaced, removed key gone, persona redaction restored.
    client = FakeClient(["A3"])
    chat(monkeypatch, tmp_path, client, ["Q3", "exit"], "--session", "k7f2qa",
         "--profile-file", write_profile(tmp_path, {"langue": "fr"}, "p2.json"))
    system = (f"Shared rules\n\n{PROFILE_HEADER}\n- langue : fr\n\n"
              f"{persona_prompt('redaction')}") + TOOLS
    assert [m.content for m in client.requests[0][1]] == [
        system, "Q1", "A1", "Q2", "A2", "Q3"]
    assert [m.role for m in client.requests[0][1]] == [
        "system", "user", "assistant", "user", "assistant", "user"]
    _, sessions, stored_profile = stored(tmp_path)
    assert stored_profile == Profile("default", {"langue": "fr"})
    assert sessions["k7f2qa"].persona_id == "redaction"
    assert [m for _, m in contents(sessions["k7f2qa"])] == ["Q1", "A1", "Q2", "A2", "Q3", "A3"]


def test_resume_with_cleared_profile_drops_profile_block(monkeypatch, tmp_path, ids):
    ids.append("k7f2qa")
    chat(monkeypatch, tmp_path, FakeClient(["A1"]), ["Q1", "exit"],
         "--profile-file", write_profile(tmp_path, {"ton": "direct"}))
    client = FakeClient(["A2"])
    chat(monkeypatch, tmp_path, client, ["Q2", "exit"], "--session", "k7f2qa",
         "--profile-file", write_profile(tmp_path, {}, "empty.json"))
    assert client.requests[0][1][0].content == "Shared rules" + TOOLS
    assert stored(tmp_path)[2] == Profile("default", {})


def test_new_launch_creates_distinct_session_and_keeps_old_one(
    monkeypatch, tmp_path, ids, capsys
):
    ids.extend(["aaaaaa", "bbbbbb"])
    chat(monkeypatch, tmp_path, FakeClient(["A1"]), ["First", "exit"])
    client = FakeClient(["A2"])
    chat(monkeypatch, tmp_path, client, ["Second", "exit"])
    assert [m.content for m in client.requests[0][1]] == ["Shared rules" + TOOLS, "Second"]
    summaries, sessions, _ = stored(tmp_path)
    assert [s.id for s in summaries] == ["bbbbbb", "aaaaaa"]
    assert [m for _, m in contents(sessions["aaaaaa"])] == ["First", "A1"]
    capsys.readouterr()
    cli.main(["--list-sessions", "--db", str(tmp_path / "s.db")])
    assert [line.split("  ")[0] for line in capsys.readouterr().out.splitlines()] == [
        "bbbbbb", "aaaaaa"]


def test_new_session_id_avoids_existing_ids(monkeypatch, tmp_path):
    letters = iter("aaaaaa" + "aaaaaa" + "bbbbbb")
    alphabets = set()

    def choice(alphabet):
        alphabets.add(alphabet)
        return next(letters)

    monkeypatch.setattr(saved_sessions.secrets, "choice", choice)
    chat(monkeypatch, tmp_path, FakeClient(["A1"]), ["First", "exit"])
    chat(monkeypatch, tmp_path, FakeClient(["A2"]), ["Second", "exit"])
    assert sorted(s.id for s in stored(tmp_path)[0]) == ["aaaaaa", "bbbbbb"]
    assert alphabets == {saved_sessions.ID_ALPHABET}


def test_environment_persona_applies_to_new_sessions(monkeypatch, tmp_path, ids):
    ids.append("k7f2qa")
    monkeypatch.setenv("SENSAI_PERSONA", "analyse")
    client = FakeClient(["A1"])
    chat(monkeypatch, tmp_path, client, ["Q1", "exit"])
    assert client.requests[0][1][0].content == f"Shared rules\n\n{persona_prompt('analyse')}" + TOOLS
    assert stored(tmp_path)[1]["k7f2qa"].persona_id == "analyse"


def test_persona_switch_before_first_turn_is_saved_with_first_turn(
    monkeypatch, tmp_path, ids
):
    ids.append("k7f2qa")
    chat(monkeypatch, tmp_path, FakeClient(["A1"]), ["/persona analyse", "Q1", "exit"],
         "--persona", "redaction")
    assert stored(tmp_path)[1]["k7f2qa"].persona_id == "analyse"


def test_resumed_untitled_session_gets_title_once_from_first_stored_exchange(
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
def test_profile_not_written_when_session_resolution_fails(
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


def test_profile_block_keeps_stored_key_order(monkeypatch, tmp_path, ids):
    ids.extend(["aaaaaa", "bbbbbb"])
    client = FakeClient(["A1"])
    chat(monkeypatch, tmp_path, client, ["Q1", "exit"],
         "--profile-file", write_profile(tmp_path, {"zeta": "1", "alpha": "2"}))
    client = FakeClient(["A2"])
    chat(monkeypatch, tmp_path, client, ["Q2", "exit"])
    assert client.requests[0][1][0].content == (
        f"Shared rules\n\n{PROFILE_HEADER}\n- zeta : 1\n- alpha : 2" + TOOLS)


def test_profile_is_creator_scoped(monkeypatch, tmp_path, ids):
    ids.extend(["aaaaaa", "bbbbbb"])
    chat(monkeypatch, tmp_path, FakeClient(["A"]), ["Q", "exit"], "--creator", "alice",
         "--profile-file", write_profile(tmp_path, {"ton": "alice"}))
    client = FakeClient(["A"])
    chat(monkeypatch, tmp_path, client, ["Q", "exit"], "--creator", "bob")
    assert client.requests[0][1][0].content == "Shared rules" + TOOLS


# --- Isolation and early errors ----------------------------------------------------------

def test_same_id_two_creators_titles_and_deletes_are_isolated(monkeypatch, tmp_path, ids):
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
def test_invalid_ids_fail_before_client(monkeypatch, tmp_path, argv, message):
    no_client(monkeypatch)
    with pytest.raises(SystemExit, match=message):
        cli.main(["model", *base_argv(tmp_path), *argv])


def test_corrupt_stored_session_fails_before_client(monkeypatch, tmp_path, ids):
    ids.append("k7f2qa")
    chat(monkeypatch, tmp_path, FakeClient(["A"]), ["Q", "exit"])
    connection = sqlite3.connect(tmp_path / "s.db")
    connection.execute("UPDATE sessions SET messages = '{not json'")
    connection.commit()
    connection.close()
    no_client(monkeypatch)
    with pytest.raises(SystemExit, match="^error: invalid stored session messages$"):
        cli.main(["model", *base_argv(tmp_path), "--session", "k7f2qa"])


def test_unknown_saved_persona_error_is_before_client_with_custom_catalogue(
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


def test_list_personas_does_not_touch_storage(monkeypatch, tmp_path, capsys):
    no_client(monkeypatch)
    cli.main(["--list-personas", "--db", str(tmp_path / "s.db")])
    assert "analyse" in capsys.readouterr().out
    assert not (tmp_path / "s.db").exists()


def test_list_sessions_on_missing_database_creates_no_file(monkeypatch, tmp_path, capsys):
    no_client(monkeypatch)
    cli.main(["--list-sessions", "--db", str(tmp_path / "missing.db")])
    assert capsys.readouterr().out == ""
    assert not (tmp_path / "missing.db").exists()


def test_list_dates_are_utc_last_update(monkeypatch, tmp_path, capsys, ids):
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

def test_meta_failure_rolls_back_whole_turn_and_chat_continues(
    monkeypatch, tmp_path, capsys, ids
):
    ids.append("k7f2qa")
    ticks = count(1)

    def now():
        tick = next(ticks)
        if tick == 2:  # call 1 is the fresh-database migration, call 2 the first save
            raise sqlite3.OperationalError("disk I/O error")
        return f"2026-10-14T15:{tick:02d}:00+00:00"

    monkeypatch.setattr(sqlite_store, "_now", now)
    seen = []
    client = FakeClient(["A1"], ["A2"])
    chat(monkeypatch, tmp_path, client, ["Q1", "Q2", "exit"],
         on_read=lambda: seen.append(raw_rows(tmp_path)))
    out = capsys.readouterr().out
    assert "error: session not saved:" in out and "disk I/O error" in out
    assert seen[1] == ([], [])  # the sessions upsert was rolled back with the meta insert
    _, sessions, _ = stored(tmp_path)
    assert [m for _, m in contents(sessions["k7f2qa"])] == ["Q1", "A1", "Q2", "A2"]


def test_persona_switch_save_failure_is_reported_and_chat_continues(
    monkeypatch, tmp_path, capsys, ids
):
    ids.append("k7f2qa")
    original = sqlite_store._SessionStore.save
    calls = count()

    def save(self, snapshot):
        if next(calls) == 1:
            raise StorageError("locked")
        original(self, snapshot)

    monkeypatch.setattr(sqlite_store._SessionStore, "save", save)
    client = FakeClient(["A1"], ["A2"])
    chat(monkeypatch, tmp_path, client, ["Q1", "/persona analyse", "Q2", "exit"])
    assert "error: session not saved: locked" in capsys.readouterr().out
    _, sessions, _ = stored(tmp_path)
    assert sessions["k7f2qa"].persona_id == "analyse"
    assert [m for _, m in contents(sessions["k7f2qa"])] == ["Q1", "A1", "Q2", "A2"]


def test_title_save_failure_is_reported_without_stopping_chat(
    monkeypatch, tmp_path, capsys, ids
):
    ids.append("k7f2qa")
    original = sqlite_store._SessionStore.set_title
    failures = [StorageError("busy")]

    def set_title(self, session_id, title):
        if failures:
            raise failures.pop()
        original(self, session_id, title)

    monkeypatch.setattr(sqlite_store._SessionStore, "set_title", set_title)
    chat(monkeypatch, tmp_path, FakeClient(["A1"], ["A2"]), ["Q1", "Q2", "exit"])
    assert "error: session title not saved: busy" in capsys.readouterr().out
    summaries, sessions, _ = stored(tmp_path)
    assert summaries[0].title == "Q1"
    assert len(sessions["k7f2qa"].messages) == 4


def test_the_shared_sample_profile_seeds_only_a_creator_without_one(tmp_path):
    sample = tmp_path / "profile.json"
    sample.write_text('{"voice": "warm"}', encoding="utf-8")
    saved = {}

    class Profiles:
        load = staticmethod(lambda name: saved.get(name))
        save = staticmethod(lambda profile: saved.__setitem__(profile.id, profile))

    saved_sessions.seed_profile(Profiles, sample)
    assert saved["default"].preferences == {"voice": "warm"}
    saved["default"] = Profile("default", {"voice": "mine"})
    saved_sessions.seed_profile(Profiles, sample)
    assert saved["default"].preferences == {"voice": "mine"}
    saved_sessions.seed_profile(Profiles, tmp_path / "missing.json")
