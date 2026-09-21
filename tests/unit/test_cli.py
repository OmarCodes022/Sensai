import pytest

from sensai.cli import parse_args
from sensai.settings import Settings


def test_cli_model_argument_overrides_settings():
    args = parse_args(Settings(_env_file=None, SENSAI_MODEL="env-model"), ["arg-model"])
    assert args.model == "arg-model"


def test_cli_requires_a_model(monkeypatch):
    monkeypatch.delenv("SENSAI_MODEL", raising=False)
    with pytest.raises(SystemExit):
        parse_args(Settings(_env_file=None), [])
