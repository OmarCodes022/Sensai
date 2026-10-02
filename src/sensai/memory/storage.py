"""Creator-bound, restart-safe SQLite implementations of the storage ports."""

import json
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, TypeVar

from sensai.core.contracts import (
    CancellationToken,
    Fact,
    PortError,
    Profile,
    SessionSnapshot,
)
from sensai.core.messages import Message

SCHEMA_VERSION = 2
_T = TypeVar("_T")


class StorageError(PortError):
    """A repository operation failed without exposing stored content."""


class InvalidStorageId(StorageError, ValueError):
    """A creator, session, profile, fact, or persona identifier is invalid."""


class UnsupportedStorageSchema(StorageError):
    """The database is not a supported Sensai storage schema."""


def _id(value: str, name: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 255
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise InvalidStorageId(f"invalid {name} id")
    return value


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def _decode(value: str, kind: str) -> object:
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        raise StorageError(f"invalid stored {kind}") from None


def _validate_table(connection: sqlite3.Connection, name: str, columns: tuple[str, ...], keys: tuple[str, ...]) -> None:
    info = connection.execute(f"PRAGMA table_info({name})").fetchall()
    if tuple(row[1] for row in info) != columns or tuple(
        row[1] for row in sorted(info, key=lambda row: row[5]) if row[5]
    ) != keys:
        raise UnsupportedStorageSchema(f"incompatible {name} table")


class StorageRepository:
    """Own one SQLite connection; call for_creator() to get isolated port adapters.

    Connections and their adapters are single-threaded. Separate repository
    instances may open the same database file.
    """

    def __init__(self, path: str | Path):
        self._connection = sqlite3.connect(path, isolation_level=None)
        self._active = False
        self._rollback_only = False
        self._cancellation: CancellationToken | None = None
        try:
            self._migrate()
        except BaseException:
            self._connection.close()
            raise

    def _migrate(self) -> None:
        connection = self._connection
        started = False
        try:
            connection.execute("BEGIN IMMEDIATE")
            started = True
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version == 0:
                tables = connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' "
                    "AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
                if tables:
                    raise UnsupportedStorageSchema("unversioned database has existing tables")
                connection.execute(
                    "CREATE TABLE sessions ("
                    "creator_id TEXT NOT NULL, session_id TEXT NOT NULL, "
                    "messages TEXT NOT NULL, persona_id TEXT, "
                    "PRIMARY KEY (creator_id, session_id))"
                )
                connection.execute(
                    "CREATE TABLE profiles ("
                    "creator_id TEXT NOT NULL, profile_id TEXT NOT NULL, "
                    "preferences TEXT NOT NULL, "
                    "PRIMARY KEY (creator_id, profile_id))"
                )
                version = 1
            if version not in (1, SCHEMA_VERSION):
                raise UnsupportedStorageSchema(f"unsupported storage version {version}")
            _validate_table(
                connection, "sessions",
                ("creator_id", "session_id", "messages", "persona_id"),
                ("creator_id", "session_id"),
            )
            _validate_table(
                connection, "profiles",
                ("creator_id", "profile_id", "preferences"),
                ("creator_id", "profile_id"),
            )
            if version == 1:
                connection.execute(
                    "CREATE TABLE facts ("
                    "creator_id TEXT NOT NULL, profile_id TEXT NOT NULL, "
                    "fact_id TEXT NOT NULL, text TEXT NOT NULL, source TEXT NOT NULL, "
                    "PRIMARY KEY (creator_id, profile_id, fact_id))"
                )
            _validate_table(
                connection, "facts",
                ("creator_id", "profile_id", "fact_id", "text", "source"),
                ("creator_id", "profile_id", "fact_id"),
            )
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            connection.execute("COMMIT")
        except BaseException:
            if started:
                connection.execute("ROLLBACK")
            raise

    def for_creator(self, creator_id: str) -> "CreatorStorage":
        """Bind every port operation to an immutable, validated creator ID."""
        return CreatorStorage(self, creator_id)

    def _check_cancelled(self) -> None:
        if self._cancellation is not None:
            self._cancellation.raise_if_cancelled()

    @contextmanager
    def transaction(self, cancellation: CancellationToken | None = None) -> Iterator[None]:
        """Atomically group port calls; exceptions and cancellation roll back all writes."""
        if self._active:
            raise StorageError("nested storage transactions are not supported")
        if cancellation is not None:
            cancellation.raise_if_cancelled()
        self._connection.execute("BEGIN IMMEDIATE")
        self._active = True
        self._cancellation = cancellation
        self._rollback_only = False
        try:
            yield
            self._check_cancelled()
            if self._rollback_only:
                raise StorageError("storage transaction rolled back after a failed operation")
            self._connection.execute("COMMIT")
        except BaseException:
            self._connection.execute("ROLLBACK")
            raise
        finally:
            self._active = False
            self._cancellation = None
            self._rollback_only = False

    def _run(self, operation: Callable[[], _T], *, write: bool = False) -> _T:
        def perform() -> _T:
            try:
                self._check_cancelled()
                result = operation()
                self._check_cancelled()
                return result
            except BaseException:
                if self._active:
                    self._rollback_only = True
                raise

        if self._active:
            return perform()
        if write:
            with self.transaction():
                return perform()
        return perform()

    def close(self) -> None:
        if self._active:
            raise StorageError("cannot close during a storage transaction")
        self._connection.close()

    def __enter__(self) -> "StorageRepository":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class CreatorStorage:
    """Creator-specific port factory; IDs never substitute for creator context."""

    def __init__(self, repository: StorageRepository, creator_id: str):
        creator_id = _id(creator_id, "creator")
        self.sessions = _SessionStore(repository, creator_id)
        self.profiles = _ProfileStore(repository, creator_id)
        self.facts = _FactStore(repository, creator_id)


class _SessionStore:
    def __init__(self, repository: StorageRepository, creator_id: str):
        self._repository = repository
        self._creator_id = creator_id

    def load(self, session_id: str) -> SessionSnapshot | None:
        def read() -> SessionSnapshot | None:
            _id(session_id, "session")
            row = self._repository._connection.execute(
                "SELECT messages, persona_id FROM sessions "
                "WHERE creator_id = ? AND session_id = ?",
                (self._creator_id, session_id),
            ).fetchone()
            if row is None:
                return None
            try:
                messages = _decode(row[0], "session messages")
                if not isinstance(messages, list):
                    raise ValueError
                return SessionSnapshot(
                    session_id,
                    tuple(Message.model_validate(message) for message in messages),
                    row[1],
                )
            except (TypeError, ValueError):
                raise StorageError("invalid stored session messages") from None

        return self._repository._run(read)

    def save(self, session: SessionSnapshot) -> None:
        def write() -> None:
            if not isinstance(session, SessionSnapshot):
                raise StorageError("expected a session snapshot")
            session_id = _id(session.id, "session")
            if session.persona_id is not None:
                _id(session.persona_id, "persona")
            if not isinstance(session.messages, tuple) or not all(
                isinstance(message, Message) for message in session.messages
            ):
                raise StorageError("expected a tuple of messages")
            messages = _json([message.model_dump() for message in session.messages])
            self._repository._connection.execute(
                "INSERT INTO sessions (creator_id, session_id, messages, persona_id) "
                "VALUES (?, ?, ?, ?) ON CONFLICT (creator_id, session_id) "
                "DO UPDATE SET messages = excluded.messages, persona_id = excluded.persona_id",
                (self._creator_id, session_id, messages, session.persona_id),
            )

        self._repository._run(write, write=True)

    def delete(self, session_id: str) -> None:
        def remove() -> None:
            _id(session_id, "session")
            self._repository._connection.execute(
                "DELETE FROM sessions WHERE creator_id = ? AND session_id = ?",
                (self._creator_id, session_id),
            )

        self._repository._run(remove, write=True)


class _ProfileStore:
    def __init__(self, repository: StorageRepository, creator_id: str):
        self._repository = repository
        self._creator_id = creator_id

    def load(self, profile_id: str) -> Profile | None:
        def read() -> Profile | None:
            _id(profile_id, "profile")
            row = self._repository._connection.execute(
                "SELECT preferences FROM profiles WHERE creator_id = ? AND profile_id = ?",
                (self._creator_id, profile_id),
            ).fetchone()
            if row is None:
                return None
            preferences = _decode(row[0], "profile preferences")
            if not isinstance(preferences, dict) or not all(
                isinstance(key, str) and isinstance(value, str)
                for key, value in preferences.items()
            ):
                raise StorageError("invalid stored profile preferences")
            return Profile(profile_id, preferences)

        return self._repository._run(read)

    def save(self, profile: Profile) -> None:
        def write() -> None:
            if not isinstance(profile, Profile):
                raise StorageError("expected a profile")
            profile_id = _id(profile.id, "profile")
            if not isinstance(profile.preferences, Mapping):
                raise StorageError("expected string preferences")
            preferences = dict(profile.preferences)
            if not all(
                isinstance(key, str) and isinstance(value, str)
                for key, value in preferences.items()
            ):
                raise StorageError("expected string preferences")
            payload = _json(preferences)
            self._repository._connection.execute(
                "INSERT INTO profiles (creator_id, profile_id, preferences) "
                "VALUES (?, ?, ?) ON CONFLICT (creator_id, profile_id) "
                "DO UPDATE SET preferences = excluded.preferences",
                (self._creator_id, profile_id, payload),
            )

        self._repository._run(write, write=True)

    def delete(self, profile_id: str) -> None:
        def remove() -> None:
            _id(profile_id, "profile")
            self._repository._connection.execute(
                "DELETE FROM facts WHERE creator_id = ? AND profile_id = ?",
                (self._creator_id, profile_id),
            )
            self._repository._connection.execute(
                "DELETE FROM profiles WHERE creator_id = ? AND profile_id = ?",
                (self._creator_id, profile_id),
            )

        self._repository._run(remove, write=True)


class _FactStore:
    def __init__(self, repository: StorageRepository, creator_id: str):
        self._repository = repository
        self._creator_id = creator_id

    def list_for(self, profile_id: str) -> tuple[Fact, ...]:
        def read() -> tuple[Fact, ...]:
            _id(profile_id, "profile")
            rows = self._repository._connection.execute(
                "SELECT fact_id, text, source FROM facts "
                "WHERE creator_id = ? AND profile_id = ? ORDER BY fact_id",
                (self._creator_id, profile_id),
            )
            return tuple(Fact(*row) for row in rows)

        return self._repository._run(read)

    def upsert(self, profile_id: str, fact: Fact) -> None:
        def write() -> None:
            _id(profile_id, "profile")
            if not isinstance(fact, Fact):
                raise StorageError("expected a fact")
            fact_id = _id(fact.id, "fact")
            if not isinstance(fact.text, str) or not isinstance(fact.source, str):
                raise StorageError("expected fact text and source")
            self._repository._connection.execute(
                "INSERT INTO facts (creator_id, profile_id, fact_id, text, source) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT (creator_id, profile_id, fact_id) "
                "DO UPDATE SET text = excluded.text, source = excluded.source",
                (self._creator_id, profile_id, fact_id, fact.text, fact.source),
            )

        self._repository._run(write, write=True)

    def delete(self, profile_id: str, fact_id: str) -> None:
        def remove() -> None:
            _id(profile_id, "profile")
            _id(fact_id, "fact")
            self._repository._connection.execute(
                "DELETE FROM facts WHERE creator_id = ? AND profile_id = ? AND fact_id = ?",
                (self._creator_id, profile_id, fact_id),
            )

        self._repository._run(remove, write=True)
