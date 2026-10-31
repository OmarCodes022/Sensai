"""/campaign in the terminal: overview, schema-forced edits, approval locks with a before/after confirmation."""
import json
from pathlib import Path

import pytest

from fakes import FakeClient, scripted_terminal
from sensai.cli import main as cli

BRAND = str(Path(__file__).parents[2] / "fixtures" / "brand.json")


class Checker:
    """Replays edits as the structured client would return them."""

    def __init__(self, *edits):
        self.edits = list(edits)

    def complete(self, model, messages, schema):
        return schema(**self.edits.pop(0))


@pytest.fixture(autouse=True)
def isolated(isolated_settings, tmp_path, monkeypatch):
    (tmp_path / "prompt.txt").write_text("Shared rules", encoding="utf-8")
    monkeypatch.setenv("SENSAI_BRAND_FILE", BRAND)
    monkeypatch.setenv("SENSAI_CAMPAIGNS_DIR", str(tmp_path / "campaigns"))


def chat(monkeypatch, tmp_path, inputs, *edits, keys=()):
    monkeypatch.setattr(cli, "create_client", lambda settings: FakeClient())
    monkeypatch.setattr(cli, "OllamaStructuredClient", lambda *a, **k: Checker(*edits))
    terminal = scripted_terminal(list(inputs))
    answers = iter(keys)
    terminal.read_key = lambda self, prompt, choices, default: next(answers, default)
    monkeypatch.setattr(cli, "TerminalInput", terminal)
    cli.main(["model", "--prompt", str(tmp_path / "prompt.txt"), "--db", str(tmp_path / "s.db")])


def document(tmp_path):
    (path,) = (tmp_path / "campaigns").glob("*.json")
    return json.loads(path.read_text())


def test_overview_edit_and_approval_lock(monkeypatch, tmp_path, capsys):
    post = {"op": "add", "caption": "Hydrates skin for up to 8 hours.", "claim_ids": ["C01"]}
    chat(monkeypatch, tmp_path, ["/campaign", "/campaign posts write a post", "/campaign approve posts", "exit"], post)
    out = capsys.readouterr().out
    assert "Posts (0)" in out and "Posts: add post P1" in out and "Saved " in out and "Posts approved" in out
    doc = document(tmp_path)
    assert doc["sections"]["posts"]["status"] == "approved" and doc["sections"]["posts"]["items"][0]["id"] == "P1"


def test_an_approved_section_asks_and_only_yes_applies(monkeypatch, tmp_path, capsys):
    chat(monkeypatch, tmp_path, ["/campaign posts a", "/campaign approve posts", "/campaign posts b", "/campaign posts c", "exit"],
         {"op": "add", "caption": "First"}, {"op": "replace", "id": "P1", "caption": "Refused"},
         {"op": "replace", "id": "P1", "caption": "Accepted"}, keys=["n", "y"])
    out = capsys.readouterr().out
    assert "Posts are approved. Sensai wants to:" in out and "Action:  replace post P1" in out
    assert "Before:  'First'" in out and "After:   'Refused'" in out and "Nothing changed." in out
    doc = document(tmp_path)
    assert doc["sections"]["posts"]["items"][0]["caption"] == "Accepted" and doc["sections"]["posts"]["status"] == "approved"


def test_invalid_edits_and_run_only_sections_change_nothing(monkeypatch, tmp_path, capsys):
    chat(monkeypatch, tmp_path, ["/campaign posts claim", "/campaign calendar ghost", "/campaign report x", "exit"],
         {"op": "add", "caption": "Cures eczema", "claim_ids": ["C02"]},
         {"op": "add", "date": "2026-11-04", "time": "18:00", "post_id": "P9", "theme": "x"})
    out = capsys.readouterr().out
    assert "C02 is not approved" in out and "post P9 does not exist" in out and "filled only by the weekly run" in out
    assert document(tmp_path)["sections"]["posts"]["items"] == []
