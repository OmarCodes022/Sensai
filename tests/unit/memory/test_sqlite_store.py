"""Local SQLite storage contracts; no Ollama or filesystem outside tmp_path."""

import sqlite3
from itertools import count

import pytest

from fakes import InterruptingConnection
from sensai.core.ports import (
    CancellationToken,
    Fact,
    FactStorePort,
    OperationCancelled,
    Profile,
    ProfileStorePort,
    SessionSnapshot,
    SessionStorePort,
    SessionSummary,
)
from sensai.core.messages import Message
from sensai.memory import sqlite_store
from sensai.memory.sqlite_store import (
    SCHEMA_VERSION,
    InvalidStorageId,
    StorageError,
    StorageRepository,
    UnsupportedStorageSchema,
)
from port_assertions import (
    assert_fact_store_contract,
    assert_profile_store_contract,
    assert_session_store_contract,
)


def snapshot(text: str, *, session_id: str = "shared") -> SessionSnapshot:
    return SessionSnapshot(
        session_id,
        (
            Message(role="system", content="Private system prompt"),
            Message(role="user", content=text),
            Message(role="assistant", content=f"reply to {text}"),
        ),
        "persona",
    )


def test_port_contracts_and_restart_safe_history_and_profiles(tmp_path):
    path = tmp_path / "memory.sqlite3"
    with StorageRepository(path) as repository:
        creator = repository.for_creator("omar")
        assert isinstance(creator.sessions, SessionStorePort)
        assert isinstance(creator.profiles, ProfileStorePort)
        assert isinstance(creator.facts, FactStorePort)
        assert_session_store_contract(creator.sessions)
        assert_profile_store_contract(creator.profiles)
        assert_fact_store_contract(creator.facts)
        creator.sessions.save(snapshot("first"))
        creator.sessions.save(snapshot("second"))
        preferences = {"tone": "brief"}
        creator.profiles.save(Profile("shared", preferences))
        preferences["tone"] = "verbose"
        creator.facts.upsert("shared", Fact("fact", "known preference", "user"))
        loaded = creator.profiles.load("shared")
        assert loaded is not None
        loaded.preferences["tone"] = "changed"
        assert creator.profiles.load("shared") == Profile("shared", {"tone": "brief"})

    with StorageRepository(path) as repository:
        creator = repository.for_creator("omar")
        assert creator.sessions.load("shared") == snapshot("second")
        assert creator.profiles.load("shared") == Profile("shared", {"tone": "brief"})
        assert creator.facts.list_for("shared") == (Fact("fact", "known preference", "user"),)
        creator.profiles.delete("shared")
        assert creator.profiles.load("shared") is None
        assert creator.facts.list_for("shared") == ()
        assert creator.sessions.load("shared") == snapshot("second")


def test_same_logical_ids_are_isolated_across_creators_and_repository_instances(tmp_path):
    path = tmp_path / "shared.sqlite3"
    with StorageRepository(path) as first, StorageRepository(path) as second:
        alice = first.for_creator("alice")
        bob = second.for_creator("bob")
        alice.sessions.save(snapshot("alice"))
        alice.profiles.save(Profile("shared", {"creator": "alice"}))
        alice.facts.upsert("shared", Fact("same", "alice only", "user"))
        assert bob.sessions.load("shared") is None
        assert bob.profiles.load("shared") is None
        assert bob.facts.list_for("shared") == ()
        bob.sessions.save(snapshot("bob"))
        bob.profiles.save(Profile("shared", {"creator": "bob"}))
        bob.facts.upsert("shared", Fact("same", "bob only", "user"))
        alice.sessions.delete("shared")
        alice.profiles.delete("shared")
        alice.facts.delete("shared", "same")
        assert bob.sessions.load("shared") == snapshot("bob")
        assert bob.profiles.load("shared") == Profile("shared", {"creator": "bob"})
        assert bob.facts.list_for("shared") == (Fact("same", "bob only", "user"),)

    with StorageRepository(path) as reopened:
        assert reopened.for_creator("bob").sessions.load("shared") == snapshot("bob")
        assert reopened.for_creator("alice").sessions.load("shared") is None


def test_atomic_rollback_after_failure_and_restart(tmp_path):
    path = tmp_path / "rollback.sqlite3"
    with StorageRepository(path) as repository:
        creator = repository.for_creator("alice")
        creator.sessions.save(snapshot("committed"))
        with pytest.raises(RuntimeError, match="failed"):
            with repository.transaction():
                creator.sessions.save(snapshot("uncommitted"))
                creator.profiles.save(Profile("shared", {"tone": "brief"}))
                creator.facts.upsert("shared", Fact("f", "private", "user"))
                raise RuntimeError("failed")
        assert creator.sessions.load("shared") == snapshot("committed")
        assert creator.profiles.load("shared") is None
        assert creator.facts.list_for("shared") == ()
        with repository.transaction():
            creator.profiles.save(Profile("shared", {"tone": "saved"}))
            creator.facts.upsert("shared", Fact("f", "saved", "user"))

    with StorageRepository(path) as reopened:
        creator = reopened.for_creator("alice")
        assert creator.sessions.load("shared") == snapshot("committed")
        assert creator.profiles.load("shared") == Profile("shared", {"tone": "saved"})
        assert creator.facts.list_for("shared") == (Fact("f", "saved", "user"),)


@pytest.mark.parametrize("cancel_at", ["before", "during", "after"])
def test_cancelled_transaction_rolls_back_after_restart(tmp_path, cancel_at):
    path = tmp_path / f"{cancel_at}.sqlite3"
    token = CancellationToken()
    with StorageRepository(path) as repository:
        creator = repository.for_creator("alice")
        if cancel_at == "before":
            token.cancel()
        with pytest.raises(OperationCancelled):
            with repository.transaction(cancellation=token):
                creator.sessions.save(snapshot("new"))
                if cancel_at == "during":
                    token.cancel()
                    creator.profiles.save(Profile("shared", {"a": "b"}))
                elif cancel_at == "after":
                    creator.profiles.save(Profile("shared", {"a": "b"}))
                    token.cancel()
        assert creator.sessions.load("shared") is None
        assert creator.profiles.load("shared") is None

    with StorageRepository(path) as reopened:
        assert reopened.for_creator("alice").sessions.load("shared") is None


def test_swallowed_operation_failure_marks_transaction_rollback_only(tmp_path):
    path = tmp_path / "failed.sqlite3"
    with StorageRepository(path) as repository:
        creator = repository.for_creator("alice")
        with pytest.raises(StorageError, match="transaction rolled back"):
            with repository.transaction():
                creator.profiles.save(Profile("shared", {"tone": "brief"}))
                with pytest.raises(StorageError, match="string preferences"):
                    creator.profiles.save(Profile("other", {"wrong": 123}))
        assert creator.profiles.load("shared") is None


@pytest.mark.parametrize(
    "bad_id", ["", " \t ", "\x00", "line\nbreak", "x" * 256, None, 42]
)
def test_invalid_ids_are_explicit_and_cannot_leak_cross_creator(tmp_path, bad_id):
    with StorageRepository(tmp_path / "ids.sqlite3") as repository:
        with pytest.raises(InvalidStorageId):
            repository.for_creator(bad_id)
        creator = repository.for_creator("alice")
        operations = (
            lambda: creator.sessions.load(bad_id),
            lambda: creator.sessions.save(SessionSnapshot(bad_id, ())),
            lambda: creator.sessions.delete(bad_id),
            lambda: creator.profiles.load(bad_id),
            lambda: creator.profiles.save(Profile(bad_id, {})),
            lambda: creator.profiles.delete(bad_id),
            lambda: creator.facts.list_for(bad_id),
            lambda: creator.facts.upsert(bad_id, Fact("fact", "text", "source")),
            lambda: creator.facts.upsert("p", Fact(bad_id, "text", "source")),
            lambda: creator.facts.delete("p", bad_id),
        )
        for operation in operations:
            with pytest.raises(InvalidStorageId):
                operation()
        quoted_id = "'); DROP TABLE sessions; --"
        creator.sessions.save(snapshot("parameterized", session_id=quoted_id))
        assert creator.sessions.load(quoted_id) == snapshot("parameterized", session_id=quoted_id)


def create_v1_database(path):
    with sqlite3.connect(path) as connection:
        connection.executescript(
            "CREATE TABLE sessions ("
            "creator_id TEXT NOT NULL, session_id TEXT NOT NULL, "
            "messages TEXT NOT NULL, persona_id TEXT, "
            "PRIMARY KEY (creator_id, session_id));"
            "CREATE TABLE profiles ("
            "creator_id TEXT NOT NULL, profile_id TEXT NOT NULL, "
            "preferences TEXT NOT NULL, PRIMARY KEY (creator_id, profile_id));"
            "PRAGMA user_version = 1;"
        )
        connection.execute(
            "INSERT INTO sessions VALUES (?, ?, ?, ?)",
            ("alice", "session", '[{"role":"user","content":"old turn"}]', None),
        )
        connection.execute(
            "INSERT INTO profiles VALUES (?, ?, ?)",
            ("alice", "profile", '{"tone":"brief"}'),
        )


def test_migrate_existing_v1_db_retains_data_and_is_idempotent(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    create_v1_database(path)
    for _ in range(2):
        with StorageRepository(path) as repository:
            creator = repository.for_creator("alice")
            assert creator.sessions.load("session") == SessionSnapshot(
                "session", (Message(role="user", content="old turn"),)
            )
            assert creator.profiles.load("profile") == Profile("profile", {"tone": "brief"})
            creator.facts.upsert("profile", Fact("old", "kept", "user"))
            assert creator.facts.list_for("profile") == (Fact("old", "kept", "user"),)
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION


def test_failed_migration_preserves_v1_data_and_version(tmp_path):
    path = tmp_path / "conflict.sqlite3"
    create_v1_database(path)
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE facts (unrelated TEXT)")
    with pytest.raises(sqlite3.OperationalError, match="already exists"):
        StorageRepository(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        assert connection.execute("SELECT messages FROM sessions").fetchone()[0].find("old turn") > 0


def test_unknown_or_future_schema_refused_without_modifying_database(tmp_path):
    path = tmp_path / "unversioned.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE another_product (value TEXT)")
    with pytest.raises(UnsupportedStorageSchema, match="unversioned"):
        StorageRepository(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 0
        connection.execute("PRAGMA user_version = 100")
    with pytest.raises(UnsupportedStorageSchema, match="unsupported storage version"):
        StorageRepository(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 100


# --- Schema v3: session metadata (titles, dates), listing and v1/v2 migrations ---------

SESSIONS = (
    "CREATE TABLE sessions (creator_id TEXT NOT NULL, session_id TEXT NOT NULL, "
    "messages TEXT NOT NULL, persona_id TEXT, PRIMARY KEY (creator_id, session_id));"
    "CREATE TABLE profiles (creator_id TEXT NOT NULL, profile_id TEXT NOT NULL, "
    "preferences TEXT NOT NULL, PRIMARY KEY (creator_id, profile_id));"
)
FACTS = (
    "CREATE TABLE facts (creator_id TEXT NOT NULL, profile_id TEXT NOT NULL, "
    "fact_id TEXT NOT NULL, text TEXT NOT NULL, source TEXT NOT NULL, "
    "PRIMARY KEY (creator_id, profile_id, fact_id));"
)


def install_clock(monkeypatch):
    ticks = count(1)
    monkeypatch.setattr(sqlite_store, "_now", lambda: f"2026-10-14T15:{next(ticks):02d}:00.000000+00:00")


@pytest.fixture
def clock(monkeypatch):
    install_clock(monkeypatch)


def turn(text):
    return (Message(role="user", content=text), Message(role="assistant", content=f"re {text}"))


def legacy_database(path, version):
    with sqlite3.connect(path) as connection:
        connection.executescript(SESSIONS + (FACTS if version == 2 else "") +
                                 f"PRAGMA user_version = {version};")
        connection.executemany("INSERT INTO sessions VALUES (?, ?, ?, ?)", [
            ("alice", "old", '[{"role":"user","content":"old turn"}]', "analyse"),
            ("bob", "old", "[]", None),
        ])
        connection.execute("INSERT INTO profiles VALUES ('alice', 'default', '{\"tone\":\"brief\"}')")
        if version == 2:
            connection.execute("INSERT INTO facts VALUES ('alice', 'default', 'f', 'kept', 'user')")
    connection.close()


def dump(path):
    with sqlite3.connect(path) as connection:
        tables = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
        rows = {table: sorted(connection.execute(f"SELECT * FROM {table}")) for table in tables}
        version = connection.execute("PRAGMA user_version").fetchone()[0]
    connection.close()
    return version, rows


@pytest.mark.parametrize("version", [1, 2])
def test_storage_v3_migration_keeps_rows_and_is_idempotent(tmp_path, clock, version):
    path = tmp_path / f"v{version}.sqlite3"
    legacy_database(path, version)
    _, before = dump(path)
    for _ in range(2):
        with StorageRepository(path) as repository:
            alice = repository.for_creator("alice")
            assert alice.sessions.load("old") == SessionSnapshot(
                "old", (Message(role="user", content="old turn"),), "analyse")
            assert alice.sessions.list() == (SessionSummary(
                "old", None, "2026-10-14T15:01:00.000000+00:00",
                "2026-10-14T15:01:00.000000+00:00"),)
            assert [s.id for s in repository.for_creator("bob").sessions.list()] == ["old"]
    version_after, after = dump(path)
    assert version_after == SCHEMA_VERSION == 3
    for table, rows in before.items():
        assert after[table] == rows
    assert after["session_meta"] == [
        ("alice", "old", None, "2026-10-14T15:01:00.000000+00:00", "2026-10-14T15:01:00.000000+00:00"),
        ("bob", "old", None, "2026-10-14T15:01:00.000000+00:00", "2026-10-14T15:01:00.000000+00:00"),
    ]


@pytest.mark.parametrize("version", [1, 2])
def test_storage_v3_failed_migration_leaves_version_and_data_intact(tmp_path, version):
    path = tmp_path / "conflict.sqlite3"
    legacy_database(path, version)
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE session_meta (unrelated TEXT)")
    connection.close()
    before = dump(path)
    with pytest.raises(sqlite3.OperationalError, match="already exists"):
        StorageRepository(path)
    assert dump(path) == before
    assert before[0] == version


def test_storage_v3_unknown_versions_and_incompatible_meta_refused(tmp_path):
    path = tmp_path / "future.sqlite3"
    legacy_database(path, 2)
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version = 4")
    connection.close()
    with pytest.raises(UnsupportedStorageSchema, match="unsupported storage version 4"):
        StorageRepository(path)
    assert dump(path)[0] == 4
    bad = tmp_path / "bad-meta.sqlite3"
    legacy_database(bad, 2)
    with sqlite3.connect(bad) as connection:
        connection.executescript("CREATE TABLE session_meta (creator_id TEXT, session_id TEXT);"
                                 "PRAGMA user_version = 3;")
    connection.close()
    with pytest.raises(UnsupportedStorageSchema, match="incompatible session_meta"):
        StorageRepository(bad)


def test_session_list_is_creator_scoped_sorted_with_exact_titles_and_dates(tmp_path, monkeypatch):
    path = tmp_path / "list.sqlite3"
    with StorageRepository(path) as repository:
        install_clock(monkeypatch)
        alice = repository.for_creator("alice").sessions
        bob = repository.for_creator("bob").sessions
        alice.save(SessionSnapshot("aaaaaa", turn("one")))      # 15:01
        bob.save(SessionSnapshot("aaaaaa", turn("bob")))        # 15:02
        alice.save(SessionSnapshot("bbbbbb", turn("two")))      # 15:03
        alice.set_title("aaaaaa", "Premier titre")
        alice.save(SessionSnapshot("aaaaaa", turn("one") + turn("again"), "analyse"))  # 15:04
        assert alice.list() == (
            SessionSummary("aaaaaa", "Premier titre", "2026-10-14T15:01:00.000000+00:00",
                           "2026-10-14T15:04:00.000000+00:00"),
            SessionSummary("bbbbbb", None, "2026-10-14T15:03:00.000000+00:00",
                           "2026-10-14T15:03:00.000000+00:00"),
        )
        assert bob.list() == (SessionSummary("aaaaaa", None, "2026-10-14T15:02:00.000000+00:00",
                                             "2026-10-14T15:02:00.000000+00:00"),)
        with pytest.raises(StorageError, match="unknown session"):
            bob.set_title("bbbbbb", "Not bob's")
        alice.delete("aaaaaa")
        assert [s.id for s in alice.list()] == ["bbbbbb"]
        assert bob.list()[0].id == "aaaaaa"
    with StorageRepository(path) as reopened:
        assert [s.id for s in reopened.for_creator("alice").sessions.list()] == ["bbbbbb"]
        with sqlite3.connect(path) as connection:
            assert connection.execute(
                "SELECT count(*) FROM session_meta WHERE creator_id = 'alice'").fetchone() == (1,)
        connection.close()


def test_session_equal_dates_sort_by_id_and_title_validation(tmp_path, monkeypatch):
    monkeypatch.setattr(sqlite_store, "_now", lambda: "2026-10-14T15:00:00.000000+00:00")
    with StorageRepository(tmp_path / "ties.sqlite3") as repository:
        sessions = repository.for_creator("alice").sessions
        for session_id in ("zzzzzz", "mmmmmm", "aaaaaa"):
            sessions.save(SessionSnapshot(session_id, turn(session_id)))
        assert [s.id for s in sessions.list()] == ["aaaaaa", "mmmmmm", "zzzzzz"]
        for title in ("", "  \n", None, 3):
            with pytest.raises(StorageError, match="nonempty session title"):
                sessions.set_title("aaaaaa", title)
        with pytest.raises(InvalidStorageId):
            sessions.set_title("", "Titre")
        with pytest.raises(StorageError, match="unknown session"):
            sessions.set_title("absent", "Titre")
        assert all(s.title is None for s in sessions.list())


def test_session_meta_write_is_atomic_with_session_save(tmp_path, monkeypatch):
    with StorageRepository(tmp_path / "atomic.sqlite3") as repository:
        sessions = repository.for_creator("alice").sessions
        monkeypatch.setattr(sqlite_store, "_now", lambda: (_ for _ in ()).throw(RuntimeError("clock")))
        with pytest.raises(RuntimeError, match="clock"):
            sessions.save(SessionSnapshot("aaaaaa", turn("lost")))
        assert sessions.load("aaaaaa") is None and sessions.list() == ()


def assert_other_connection_can_write(path, session_id):
    with StorageRepository(path) as other:
        other.for_creator("bob").sessions.save(SessionSnapshot(session_id, turn("other")))


def test_interrupt_after_begin_leaves_no_open_transaction(tmp_path):
    path = tmp_path / "begin.sqlite3"
    with StorageRepository(path) as repository:
        sessions = repository.for_creator("alice").sessions
        repository._connection = InterruptingConnection(repository._connection, "BEGIN IMMEDIATE")
        with pytest.raises(KeyboardInterrupt):
            sessions.save(SessionSnapshot("aaaaaa", turn("lost")))
        assert not repository._connection.in_transaction and not repository._active
        assert_other_connection_can_write(path, "bbbbbb")
        sessions.save(SessionSnapshot("aaaaaa", turn("kept")))
        assert sessions.load("aaaaaa") == SessionSnapshot("aaaaaa", turn("kept"))


def test_stale_open_transaction_is_rolled_back_before_next_write(tmp_path):
    path = tmp_path / "stale.sqlite3"
    with StorageRepository(path) as repository:
        sessions = repository.for_creator("alice").sessions
        repository._connection.execute("BEGIN IMMEDIATE")  # BEGIN ran, bookkeeping never did
        repository._connection.execute(
            "INSERT INTO sessions VALUES ('alice', 'ghost', '[]', NULL)")
        sessions.save(SessionSnapshot("aaaaaa", turn("kept")))
        assert not repository._connection.in_transaction
        assert_other_connection_can_write(path, "bbbbbb")
        assert sessions.load("ghost") is None and [s.id for s in sessions.list()] == ["aaaaaa"]
        with repository.transaction():
            with pytest.raises(StorageError, match="nested"):
                with repository.transaction():
                    pass
            sessions.save(SessionSnapshot("cccccc", turn("inside")))
        assert sessions.load("cccccc") is not None


def test_interrupt_after_commit_propagates_with_row_committed(tmp_path):
    path = tmp_path / "commit.sqlite3"
    with StorageRepository(path) as repository:
        sessions = repository.for_creator("alice").sessions
        repository._connection = InterruptingConnection(repository._connection, "COMMIT")
        with pytest.raises(KeyboardInterrupt):
            sessions.save(SessionSnapshot("aaaaaa", turn("committed")))
        assert not repository._connection.in_transaction and not repository._active
        with StorageRepository(path) as other:
            assert other.for_creator("alice").sessions.load("aaaaaa") == SessionSnapshot(
                "aaaaaa", turn("committed"))
        assert_other_connection_can_write(path, "bbbbbb")
        sessions.save(SessionSnapshot("aaaaaa", turn("again")))
        assert sessions.load("aaaaaa") == SessionSnapshot("aaaaaa", turn("again"))
