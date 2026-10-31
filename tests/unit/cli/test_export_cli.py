"""/export in the terminal, and the automatic campaign export after each saved change."""
import json
from pathlib import Path

import pytest

from fakes import FakeClient, scripted_terminal
from sensai.cli import main as cli

BRAND = str(Path(__file__).parents[2] / "fixtures" / "brand.json")


class Checker:
    def __init__(self, *edits):
        self.edits = list(edits)

    def complete(self, model, messages, schema):
        return schema(**self.edits.pop(0))


@pytest.fixture(autouse=True)
def isolated(isolated_settings, tmp_path, monkeypatch):
    (tmp_path / "prompt.txt").write_text("Shared rules", encoding="utf-8")
    monkeypatch.setenv("SENSAI_BRAND_FILE", BRAND)
    monkeypatch.setenv("SENSAI_CAMPAIGNS_DIR", str(tmp_path / "campaigns"))
    monkeypatch.setenv("SENSAI_EXPORTS_DIR", str(tmp_path / "exports"))


def chat(monkeypatch, tmp_path, client, inputs, *edits):
    monkeypatch.setattr(cli, "create_client", lambda settings: client)
    monkeypatch.setattr(cli, "OllamaStructuredClient", lambda *a, **k: Checker(*edits))
    monkeypatch.setattr(cli, "TerminalInput", scripted_terminal(inputs))
    cli.main(["model", "--prompt", str(tmp_path / "prompt.txt"), "--db", str(tmp_path / "s.db")])


def test_export_writes_the_conversation_and_says_when_there_is_no_campaign(monkeypatch, tmp_path, capsys):
    chat(monkeypatch, tmp_path, FakeClient(["Hello there."]), ["Hi", "/export", "exit"])
    out = capsys.readouterr().out
    assert "Conversation: " in out and "No campaign yet" in out
    (session,) = (tmp_path / "exports" / "sessions").glob("*.json")
    assert json.loads(session.read_text())["messages"][1]["content"] == "Hello there."


def test_a_campaign_change_is_exported_automatically(monkeypatch, tmp_path, capsys):
    chat(monkeypatch, tmp_path, FakeClient(), ["/campaign posts write one", "/export", "exit"],
         {"op": "add", "caption": "Hydrates skin for up to 8 hours.", "claim_ids": ["C01"]})
    out = capsys.readouterr().out
    assert out.count("Exported campaign: ") == 2
    (md,) = (tmp_path / "exports" / "campaigns").glob("*.md")
    assert "Hydrates skin for up to 8 hours." in md.read_text()


def test_a_write_error_does_not_stop_the_chat(monkeypatch, tmp_path, capsys):
    (tmp_path / "exports").write_text("not a folder")
    chat(monkeypatch, tmp_path, FakeClient(["Hello."], ["Still here."]), ["Hi", "/export", "Again", "exit"])
    out = capsys.readouterr().out
    assert "error: conversation not exported" in out and "Still here." in out
