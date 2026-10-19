"""Keep CLI session storage out of the repository and title requests off scripted clients."""

import pytest

from sensai.app import cli, conversations

REAL_GENERATE_TITLE = conversations.generate_title
REAL_DEFAULT_DB_PATH = cli.DEFAULT_DB_PATH


@pytest.fixture(autouse=True)
def isolated_session_storage(monkeypatch, tmp_path_factory):
    for name in ("SENSAI_CREATOR", "SENSAI_PROFILE_FILE"):
        monkeypatch.delenv(name, raising=False)
    path = str(tmp_path_factory.mktemp("session-db") / "sensai.sqlite3")
    monkeypatch.setattr(cli, "DEFAULT_DB_PATH", path)
    # Child interpreters (launcher signal tests) inherit the environment, not patches.
    monkeypatch.setenv("SENSAI_DB", path)
    monkeypatch.setattr(conversations, "generate_title", lambda *args, **kwargs: None)


@pytest.fixture
def real_titles(monkeypatch):
    """Opt back into the separate title request (T29 tests)."""
    monkeypatch.setattr(conversations, "generate_title", REAL_GENERATE_TITLE)


@pytest.fixture
def real_default_db_path():
    """The unpatched cli.DEFAULT_DB_PATH, captured at import before any redirection."""
    return REAL_DEFAULT_DB_PATH
