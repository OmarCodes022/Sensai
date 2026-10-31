"""Shared unit-test fixtures.

Every test keeps CLI session storage out of the repository and title requests off
scripted clients; tests opt into the other fixtures explicitly.
"""

import os

import pytest

from sensai.cli import main as cli
from sensai.chat import personas, saved_sessions
from sensai.settings import Settings

REAL_GENERATE_TITLE = saved_sessions.generate_title
REAL_DEFAULT_DB_PATH = cli.DEFAULT_DB_PATH
REAL_SETUP_DOCS = cli._setup_docs


@pytest.fixture(autouse=True)
def isolated_session_storage(monkeypatch, tmp_path_factory):
    for name in ("SENSAI_CREATOR", "SENSAI_PROFILE_FILE"):
        monkeypatch.delenv(name, raising=False)
    path = str(tmp_path_factory.mktemp("session-db") / "sensai.sqlite3")
    monkeypatch.setattr(cli, "DEFAULT_DB_PATH", path)
    # Child interpreters (launcher signal tests) inherit the environment, not patches.
    monkeypatch.setenv("SENSAI_DB", path)
    monkeypatch.setattr(saved_sessions, "generate_title", lambda *args, **kwargs: None)


@pytest.fixture(autouse=True)
def no_shared_sample_files(monkeypatch):
    """The repository's data/profile.json and data/personas.json must not leak into tests."""
    monkeypatch.setattr(saved_sessions, "DEFAULT_PROFILE_FILE", "no-such-profile.json")
    monkeypatch.setattr(personas, "DEFAULT_FILE", "no-such-personas.json")


@pytest.fixture(autouse=True)
def no_web(monkeypatch):
    """Unit tests never reach the internet: a web search sees a network error unless a test fakes it."""
    import requests
    from sensai import search

    def offline(*args, **kwargs):
        raise requests.ConnectionError("network disabled in unit tests")
    monkeypatch.setattr(search.requests, "get", offline)
    monkeypatch.setattr(search.requests, "post", offline)


@pytest.fixture(autouse=True)
def no_document_search(monkeypatch):
    """The repository's data/docs would otherwise be embedded through a real Ollama in every chat."""
    monkeypatch.setattr(cli, "_setup_docs", lambda *args, **kwargs: None)


@pytest.fixture
def real_setup_docs(monkeypatch):
    """Opt back into the real document library wiring."""
    monkeypatch.setattr(cli, "_setup_docs", REAL_SETUP_DOCS)


@pytest.fixture
def isolated_settings(monkeypatch):
    """Ignore the developer's SENSAI_*/OLLAMA_HOST environment, .env file and data/ in cli.main."""
    for name in list(os.environ):
        if name.startswith("SENSAI_") or name == "OLLAMA_HOST":
            monkeypatch.delenv(name, raising=False)
    # The repository's data/ would otherwise be the default data folder (listed in the prompt).
    monkeypatch.setenv("SENSAI_DATA_DIR", "")
    monkeypatch.setattr(cli, "Settings", lambda: Settings(_env_file=None))


@pytest.fixture
def real_titles(monkeypatch):
    """Opt back into the separate title request."""
    monkeypatch.setattr(saved_sessions, "generate_title", REAL_GENERATE_TITLE)


@pytest.fixture
def real_default_db_path():
    """The unpatched cli.DEFAULT_DB_PATH, captured at import before any redirection."""
    return REAL_DEFAULT_DB_PATH
