"""T54, end to end in the terminal: `--weekly-run` on fictional inputs, then a chat that sees the week and
exports it privately. A scripted model stands in for Ollama; no other HTTP call is made."""
import json
import shutil
from pathlib import Path

import pytest
import requests

from fakes import FakeClient, scripted_terminal
from sensai.cli import main as cli
from sensai.cli import weekly
from sensai.weekly.outputs import EntryDraft, EntryDrafts, PostDraft, PostDrafts, Reading, Suggestion

FIXTURES = Path(__file__).parents[2] / "fixtures"
ANSWERS = {
    "Reading": Reading(interpretation="A steady week."),
    "Suggestion": Suggestion(text="It suits dry skin; a dermatologist can advise on conditions."),
    "PostDrafts": PostDrafts(posts=[PostDraft(caption="Hydrates skin for up to 8 hours.", claim_ids=["C01"]),
                                    PostDraft(caption="Reduces redness in 4 weeks.", claim_ids=["C03"]),
                                    PostDraft(caption="Your evening routine?", claim_ids=[])]),
    "EntryDrafts": EntryDrafts(entries=[EntryDraft(date=d, time="18:30", post_id=p, theme="t")
                                        for d, p in (("2026-09-29", "P1"), ("2026-09-30", "P2"), ("2026-10-02", "P3"))]),
}


@pytest.fixture
def setup(isolated_settings, tmp_path, monkeypatch):
    inputs = tmp_path / "inputs"
    shutil.copytree(FIXTURES, inputs, ignore=shutil.ignore_patterns("docs"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SENSAI_BRAND_FILE", str(inputs / "brand.json"))
    monkeypatch.setenv("SENSAI_DOCS", "")
    monkeypatch.setattr(weekly, "OllamaStructuredClient",
                        lambda *a, **k: type("Scripted", (), {"complete": lambda self, m, msgs, schema: ANSWERS[schema.__name__]})())
    outgoing = []

    def record(*args, **kwargs):
        outgoing.append(args[0] if args else kwargs.get("url"))
        raise requests.ConnectionError("no network in this test")
    for name in ("get", "post"):
        monkeypatch.setattr(requests, name, record)
    return inputs, outgoing


def test_the_week_in_the_terminal_then_a_private_export(setup, tmp_path, monkeypatch, capsys):
    inputs, outgoing = setup
    with pytest.raises(SystemExit) as stopped:
        cli.main(["qwen2.5", "--weekly-run", str(inputs)])
    out = capsys.readouterr().out
    assert stopped.value.code == 0 and "Saved campaigns/2026-W40.json: nothing was sent or published." in out
    for name in ("Report", "DM replies", "Posts", "Calendar"):
        assert f"{name} " in out and "failed" not in out

    # The chat (B1) still works, and /export writes the week and the conversation to private files only.
    monkeypatch.setattr(cli, "create_client", lambda settings: FakeClient(["Sure."]))
    monkeypatch.setattr(cli, "TerminalInput", scripted_terminal(["hello", "/export", "exit"]))
    cli.main(["qwen2.5", "--db", str(tmp_path / "s.db")])
    out = capsys.readouterr().out
    assert "Sure." in out and "campaigns/2026-W40.json" in out
    exported = json.loads((tmp_path / "exports" / "campaigns" / "2026-W40.json").read_text(encoding="utf-8"))
    assert [r["case_key"] for r in exported["sections"]["replies"]["items"]] == ["Q1", "Q2"]
    assert "emma" not in json.dumps(exported).lower()
    assert [u for u in outgoing if not str(u).startswith("http://localhost:11434")] == []  # Nothing sent elsewhere.
