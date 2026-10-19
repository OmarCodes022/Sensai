"""chat.prompts: user prompt files and the packaged default prompt."""

from pathlib import Path

import pytest

from sensai.chat.prompts import load_system_prompt


def test_load_system_prompt(tmp_path):
    f = tmp_path / "p.txt"
    f.write_text("You are Sensai.\n")
    assert load_system_prompt(str(f)) == "You are Sensai."


def test_load_system_prompt_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_system_prompt(str(tmp_path / "nope.txt"))


PACKAGED = Path(__file__).resolve().parents[3] / "src" / "sensai" / "chat" / "system_prompt.txt"


def test_default_prompt_is_packaged_and_loads_from_any_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert load_system_prompt() == PACKAGED.read_text(encoding="utf-8").strip()
    assert load_system_prompt(None).startswith("You are")


def test_empty_prompt_path_uses_packaged_default():
    assert load_system_prompt("") == load_system_prompt()
