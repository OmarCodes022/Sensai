import pytest
from pydantic import ValidationError

from sensai.settings import Settings


def test_settings_read_env(monkeypatch):
    monkeypatch.setenv("SENSAI_MODEL", "x")
    monkeypatch.setenv("SENSAI_TIMEOUT", "5")
    s = Settings(_env_file=None)
    assert (s.model, s.timeout) == ("x", 5.0)


def test_settings_reject_bad_timeout(monkeypatch):
    monkeypatch.setenv("SENSAI_TIMEOUT", "0")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
