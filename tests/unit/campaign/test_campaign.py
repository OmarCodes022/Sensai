"""The campaign document: one schema-checked edit to one item, approval locks, files written atomically."""
from datetime import date
from pathlib import Path

import pytest

from sensai.campaign import CampaignError, CampaignStore, apply, approve, ask, overview, plan
from sensai.campaign.models import EntryEdit, PostEdit
from sensai.guardrails.rules import load_claims

BRAND = str(Path(__file__).parents[2] / "fixtures" / "brand.json")


@pytest.fixture
def store(tmp_path):
    return CampaignStore(str(tmp_path / "campaigns"), today=lambda: date(2026, 10, 28))


@pytest.fixture
def claims():
    return load_claims(BRAND, date(2026, 10, 28))


def test_a_new_document_is_the_coming_week_with_four_empty_sections(store):
    doc = store.latest()
    assert (doc.week, doc.start, doc.end) == ("2026-W45", "2026-11-02", "2026-11-08")
    assert Path(store.path(doc.week)).exists() and store.latest() == doc
    assert overview(doc)[1:5] == ["Posts (0)......... draft", "DM replies (0).... draft",
                                  "Report............ draft: no data yet", "Calendar (0)...... draft"]


def test_one_edit_changes_one_item_and_leaves_the_other_sections_byte_for_byte(store, claims):
    doc = store.latest()
    change = plan(doc, "posts", PostEdit(op="add", caption="Thirsty skin? Hydrates skin for up to 8 hours.", claim_ids=["C01"]), claims)
    assert change.action == "add post P1" and change.before is None
    apply(store, change)
    doc = store.latest()
    entry = plan(doc, "calendar", EntryEdit(op="add", date="2026-11-04", time="18:00", post_id="P1", theme="Launch"), claims)
    apply(store, entry)
    after = store.latest()
    assert after.sections.posts == doc.sections.posts and after.sections.calendar.items[0].id == "E1"
    replaced = plan(after, "posts", PostEdit(op="replace", id="P1", caption="New caption", claim_ids=[]), claims)
    assert (replaced.before, replaced.after) == ("Thirsty skin? Hydrates skin for up to 8 hours.", "New caption")


@pytest.mark.parametrize("section, edit, message", [
    ("posts", PostEdit(op="add", caption="It cures eczema", claim_ids=["C02"]), "C02 is not approved"),
    ("posts", PostEdit(op="add", caption="x", claim_ids=["C04"]), "C04 is not approved"),
    ("posts", PostEdit(op="replace", id="P9", caption="x"), "post P9 does not exist"),
    ("posts", PostEdit(op="add", caption=" "), "no caption"),
    ("calendar", EntryEdit(op="add", date="2026-11-04", time="18:00", post_id="P7", theme="x"), "post P7 does not exist"),
    ("calendar", EntryEdit(op="add", date="2026-12-01", time="18:00", post_id="P1", theme="x"), "outside the week"),
    ("calendar", EntryEdit(op="add", date="2026-11-04", time="25:00", post_id="P1", theme="x"), "HH:MM"),
    ("report", PostEdit(op="add", caption="x"), "filled only by the weekly run"),
    ("replies", PostEdit(op="add", caption="x"), "filled only by the weekly run"),
])
def test_invalid_edits_are_rejected_and_the_file_is_unchanged(store, claims, section, edit, message):
    doc = store.latest()
    apply(store, plan(doc, "posts", PostEdit(op="add", caption="ok"), claims))
    before = Path(store.path(doc.week)).read_bytes()
    with pytest.raises(CampaignError, match=message):
        plan(store.latest(), section, edit, claims)
    assert Path(store.path(doc.week)).read_bytes() == before


def test_approve_marks_a_section_and_a_post_used_by_the_calendar_cannot_be_removed(store, claims):
    doc = store.latest()
    apply(store, plan(doc, "posts", PostEdit(op="add", caption="ok"), claims))
    apply(store, plan(store.latest(), "calendar", EntryEdit(op="add", date="2026-11-03", time="09:00", post_id="P1", theme="t"), claims))
    doc = approve(store, store.latest(), "posts")
    assert doc.sections.posts.status == "approved" and doc.sections.posts.approved_at
    with pytest.raises(CampaignError, match="used in the calendar"):
        plan(doc, "posts", PostEdit(op="remove", id="P1", caption=""), claims)


def test_the_model_is_asked_with_the_sections_schema(store, claims):
    seen = {}

    class Checker:
        def complete(self, model, messages, schema):
            seen.update(schema=schema, text=messages[1].content)
            return schema(op="add", caption="hi")

    edit = ask(Checker(), "m", store.latest(), "posts", "write a post", claims)
    assert seen["schema"] is PostEdit and isinstance(edit, PostEdit)
    assert '"approved_claims": [{"id": "C01"' in seen["text"] and "Request: write a post" in seen["text"]
