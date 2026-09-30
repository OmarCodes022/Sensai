# Creator-bound SQLite storage (T14 / #27, T15 / #28)

`sensai.storage.StorageRepository` implements the existing `SessionStorePort`,
`ProfileStorePort`, and `FactStorePort` without changing their method signatures.
Bind the creator **once** to obtain all three ports:

```python
from sensai.contracts import CancellationToken, Profile, SessionSnapshot
from sensai.storage import StorageRepository

with StorageRepository("sensai.sqlite3") as repository:
    creator = repository.for_creator("creator-123")
    sessions = creator.sessions
    profiles = creator.profiles
    facts = creator.facts

    # Persist only a fully completed turn; B1 does not save automatically.
    sessions.save(SessionSnapshot("chat-1", completed_messages, "tutor"))
    profiles.save(Profile("default", {"tone": "brief"}))

    token = CancellationToken()
    with repository.transaction(cancellation=token):
        profiles.save(Profile("default", {"tone": "concise"}))
        # Other session, profile, and fact operations on this repository can
        # participate in the same atomic transaction.
```

`completed_messages` above is a `tuple[Message, ...]` supplied by the caller
(for example a completed `B1SessionAdapter.history`). The repository never
starts/resumes a `ChatSession`, injects preferences, or enables persistence
implicitly; those runtime/UX choices belong to T29. All port operations scope
their SQL to the immutable creator ID, including deletes and fact lookups. A
missing entry loads as `None` (facts return `()`); delete of a missing entry is
harmless. Saving a session or profile with an existing ID replaces that
creator's entry. Profile deletion also removes its creator's facts atomically.
Facts can be stored before their profile, as the original fact port permits.
Profile preferences are copied on save and load.

Transactions use SQLite `BEGIN IMMEDIATE` / `COMMIT` / `ROLLBACK`. Each port
call outside a transaction is its own atomic operation. An exception, a
cooperative `CancellationToken` checked before/after an operation or at
transaction exit, or an operation error (even if caught inside the block) rolls
back the whole transaction. Nested transactions are not supported. Close the
repository after use (or use `with`); do not share one connection across
threads. Separate repository instances can open the same file. SQLite
recovers incomplete transactions on reopening; a failure *after commit*
cannot be undone by cancellation.

The schema is versioned via SQLite `PRAGMA user_version`. New databases are
created at version **2** in one transaction. Existing version **1** databases
with `sessions(creator_id, session_id, messages, persona_id)` keyed by
`(creator_id, session_id)` and
`profiles(creator_id, profile_id, preferences)` keyed by
`(creator_id, profile_id)` migrate atomically to version 2 by adding
`facts(creator_id, profile_id, fact_id, text, source)` keyed by
`(creator_id, profile_id, fact_id)`. Session messages and profile preferences
are JSON text. Version 1 rows survive the upgrade; reopening a version 2
database does not repeat it. Unknown/future versions, unversioned databases
with existing tables, and incompatible known tables are rejected rather than
overwritten. An interrupted or failed migration leaves the original version
and data intact.

Invalid IDs (non-string, blank, control characters, or over 255 characters)
raise `InvalidStorageId`; unsupported databases raise
`UnsupportedStorageSchema`; invalid payloads or failed transactions raise
`StorageError`. These extend `PortError`. SQL values are parameterized, and
the adapter does not log prompts or profile data. **SQLite stores message
content, preferences, and facts in plaintext**; callers must protect database
files and backups. No encryption, multi-user authentication, session listing,
retention policy, or filesystem permissions are supplied by this API. A
creator ID is a scoping key, **not authentication**: callers must authorize
which creator context they bind.

`tests/unit/test_storage.py` runs disk/restart and migration scenarios under
`tmp_path`, alongside reusable port-contract assertions from
`tests/unit/test_contracts.py`. For an in-memory fake, use
`tests/fakes.py::FakeStorage`; its ports do not require SQLite or Ollama.
