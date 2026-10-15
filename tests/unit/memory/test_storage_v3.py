"""T29 schema v3: session metadata (titles, dates), listing and v1/v2 migrations."""

import sqlite3
from itertools import count

import pytest

from sensai.core.contracts import SessionSnapshot, SessionSummary
from sensai.core.messages import Message
from sensai.memory import storage
from sensai.memory.storage import (
    SCHEMA_VERSION,
    InvalidStorageId,
    StorageError,
    StorageRepository,
    UnsupportedStorageSchema,
)

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
    monkeypatch.setattr(storage, "_now", lambda: f"2026-10-14T15:{next(ticks):02d}:00.000000+00:00")


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


def test_storage_v3_list_is_creator_scoped_sorted_with_exact_titles_and_dates(tmp_path, monkeypatch):
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


def test_storage_v3_equal_dates_sort_by_id_and_title_validation(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "_now", lambda: "2026-10-14T15:00:00.000000+00:00")
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


def test_storage_v3_meta_write_is_atomic_with_session_save(tmp_path, monkeypatch):
    with StorageRepository(tmp_path / "atomic.sqlite3") as repository:
        sessions = repository.for_creator("alice").sessions
        monkeypatch.setattr(storage, "_now", lambda: (_ for _ in ()).throw(RuntimeError("clock")))
        with pytest.raises(RuntimeError, match="clock"):
            sessions.save(SessionSnapshot("aaaaaa", turn("lost")))
        assert sessions.load("aaaaaa") is None and sessions.list() == ()


class InterruptingConnection:
    """Proxy that raises KeyboardInterrupt right after given statements succeed."""

    def __init__(self, connection, *after):
        self._connection, self.after = connection, list(after)

    def execute(self, sql, *args):
        result = self._connection.execute(sql, *args)
        if self.after and sql == self.after[0]:
            self.after.pop(0)
            raise KeyboardInterrupt
        return result

    def __getattr__(self, name):
        return getattr(self._connection, name)


def assert_other_connection_can_write(path, session_id):
    with StorageRepository(path) as other:
        other.for_creator("bob").sessions.save(SessionSnapshot(session_id, turn("other")))


def test_storage_v3_interrupt_after_begin_leaves_no_open_transaction(tmp_path):
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


def test_storage_v3_stale_open_transaction_is_rolled_back_before_next_write(tmp_path):
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


def test_storage_v3_interrupt_after_commit_propagates_with_row_committed(tmp_path):
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
