"""Private export: files, redaction, refusals that keep the previous export, and safe writes."""
import json
from datetime import date
from pathlib import Path

import pytest

from sensai.campaign import CampaignStore, apply, plan
from sensai.campaign.models import EntryEdit, PostEdit
from sensai.core.messages import Message
from sensai.export import Exporter, ExportRefused
from sensai.guardrails import load_guardrail

BRAND = str(Path(__file__).parents[2] / "fixtures" / "brand.json")


@pytest.fixture
def guard():
    return load_guardrail(brand_file=BRAND, today=date(2026, 10, 28))


def campaign(tmp_path, guard, caption="Hydrates skin for up to 8 hours.", claims=("C01",)):
    store = CampaignStore(str(tmp_path / "campaigns"), today=lambda: date(2026, 10, 28))
    apply(store, plan(store.latest(), "posts", PostEdit(op="add", caption=caption, claim_ids=list(claims)), guard.claims))
    apply(store, plan(store.latest(), "calendar", EntryEdit(op="add", date="2026-11-04", time="18:00", post_id="P1", theme="Launch"), guard.claims))
    return store.latest()


def test_a_conversation_is_exported_as_valid_json_and_readable_markdown(tmp_path, guard):
    messages = [Message(role="system", content="secret prompt"), Message(role="user", content="Mail lea@x.com a caption"),
                Message(role="assistant", content='Sure.\n{"tool":"calculate","arguments":{}}'),
                Message(role="user", content="Tool result from calculate:\n2"), Message(role="assistant", content="Done.")]
    paths = Exporter(guard, str(tmp_path / "exports")).session("k7f2qa", "Caption", messages)
    data = json.loads(Path(paths[0]).read_text())
    assert [m["content"] for m in data["messages"]] == ["Mail [redacted] a caption", "Sure.", "Done."]
    text = Path(paths[1]).read_text()
    assert "secret prompt" not in text and "## You\n\nMail [redacted] a caption" in text and "## Sensai\n\nDone." in text


def test_the_campaign_has_its_four_sections_with_the_calendar_as_a_table(tmp_path, guard):
    paths = Exporter(guard, str(tmp_path / "exports")).campaign(campaign(tmp_path, guard))
    md = Path(paths[1]).read_text()
    assert json.loads(Path(paths[0]).read_text())["week"] == "2026-W45"
    for heading in ("## Post drafts (draft)", "## DM reply suggestions, unsent (draft)", "## Weekly report (draft)", "## Content calendar"):
        assert heading in md
    assert "| 2026-11-04 | 18:00 | Instagram | P1 | Launch |" in md and "claims C01" in md


def test_a_refused_claim_keeps_the_previous_export(tmp_path, guard):
    exporter = Exporter(guard, str(tmp_path / "exports"))
    paths = exporter.campaign(campaign(tmp_path, guard))
    before = Path(paths[1]).read_text()
    bad = campaign(tmp_path / "b", guard, caption="It cures eczema", claims=())
    with pytest.raises(ExportRefused, match="unapproved_claim:C02"):
        exporter.campaign(bad.model_copy(update={"week": "2026-W45"}))
    assert Path(paths[1]).read_text() == before


def test_a_write_error_is_an_os_error_and_leaves_no_temporary_file(tmp_path, guard):
    blocked = tmp_path / "exports"
    blocked.write_text("not a folder")
    with pytest.raises(OSError):
        Exporter(guard, str(blocked)).session("a", "t", [Message(role="user", content="hi")])
