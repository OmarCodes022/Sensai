import pytest

from sensai.prompts import load_system_prompt


def test_load_system_prompt(tmp_path):
    f = tmp_path / "p.txt"
    f.write_text("You are Sensai.\n")
    assert load_system_prompt(str(f)) == "You are Sensai."


def test_load_system_prompt_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_system_prompt(str(tmp_path / "nope.txt"))
