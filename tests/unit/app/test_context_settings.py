"""Optional Ollama context size is validated at configuration loading."""

import pytest
from pydantic import ValidationError

from sensai.app.settings import Settings


def test_context_length_defaults_to_server_configuration(monkeypatch):
    monkeypatch.delenv("SENSAI_CONTEXT_LENGTH", raising=False)
    assert Settings(_env_file=None).context_length is None


def test_context_length_reads_positive_integer_from_environment(monkeypatch):
    monkeypatch.setenv("SENSAI_CONTEXT_LENGTH", "8192")
    assert Settings(_env_file=None).context_length == 8192


@pytest.mark.parametrize("value", ["0", "-1", "8192.5", "true", "invalid", ""])
def test_invalid_context_length_is_rejected(monkeypatch, value):
    monkeypatch.setenv("SENSAI_CONTEXT_LENGTH", value)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
