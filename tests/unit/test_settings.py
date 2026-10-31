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


# Optional Ollama context size is validated at configuration loading.

def test_context_length_defaults_to_8192(monkeypatch):
    # Sensai's instructions take about 2,000 tokens: Ollama's usual 4096 fills after one turn.
    monkeypatch.delenv("SENSAI_CONTEXT_LENGTH", raising=False)
    assert Settings(_env_file=None).context_length == 8192


def test_context_length_reads_positive_integer_from_environment(monkeypatch):
    monkeypatch.setenv("SENSAI_CONTEXT_LENGTH", "8192")
    assert Settings(_env_file=None).context_length == 8192


@pytest.mark.parametrize("value", ["0", "-1", "8192.5", "true", "invalid", ""])
def test_invalid_context_length_is_rejected(monkeypatch, value):
    monkeypatch.setenv("SENSAI_CONTEXT_LENGTH", value)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_data_dir_defaults_to_unset(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # No ./data folder here.
    monkeypatch.delenv("SENSAI_DATA_DIR", raising=False)
    assert Settings(_env_file=None).data_dir is None


@pytest.mark.parametrize("value", ["tests/fixtures", ""])
def test_data_dir_reads_environment(monkeypatch, value):
    monkeypatch.setenv("SENSAI_DATA_DIR", value)
    assert Settings(_env_file=None).data_dir == value
