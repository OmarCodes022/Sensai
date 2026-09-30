"""Local SQLite storage contracts; no Ollama or filesystem outside tmp_path."""

import sqlite3

import pytest

from sensai.contracts import (
    CancellationToken,
    Fact,
    FactStorePort,
    OperationCancelled,
    Profile,
    ProfileStorePort,
    SessionSnapshot,
    SessionStorePort,
)
from sensai.messages import Message
from sensai.storage import (
    SCHEMA_VERSION,
    InvalidStorageId,
    StorageError,
    StorageRepository,
    UnsupportedStorageSchema,
)
from test_contracts import (
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
