"""T54, end to end in the page: fictional brand inputs -> the four saved outputs -> approval kept -> private
export, with the chat working alongside. A scripted model stands in for Ollama; any other HTTP call is
recorded, and there must be none: nothing is sent, published or shared.
"""
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from fakes import FakeClient
from sensai.weekly.outputs import EntryDraft, EntryDrafts, PostDraft, PostDrafts, Reading, Suggestion

FIXTURES = Path(__file__).parents[2] / "fixtures"
OLLAMA = "http://localhost:1"  # The web fixture's Ollama host.


def posts(*captions):
    return PostDrafts(posts=[PostDraft(caption=c, claim_ids=ids) for c, ids in captions])


WEEK_POSTS = posts(("Hydrates skin for up to 8 hours. Ready for Monday?", ["C01"]),
                   ("Reduces redness in 4 weeks. Gentle every night.", ["C03"]),
                   ("What is your evening routine?", []))
CALENDAR = EntryDrafts(entries=[EntryDraft(date=d, time="18:30", post_id=p, theme="t")
                                for d, p in (("2026-09-29", "P1"), ("2026-09-30", "P2"), ("2026-10-02", "P3"))])


class ScriptedChecker:
    """The structured model: answers by schema; `posts` can be swapped to see what an approval protects."""

    def __init__(self):
        self.posts = WEEK_POSTS

    def complete(self, model, messages, schema):
        return {"Reading": Reading(interpretation="A steady week."), "PostDrafts": self.posts, "EntryDrafts": CALENDAR,
                "Suggestion": Suggestion(text="It suits dry skin; a dermatologist can advise on conditions.")}[schema.__name__]


@pytest.fixture
def outgoing(monkeypatch):
    """Every HTTP call that is not the scripted model: there must be none."""
    calls = []

    def record(*args, **kwargs):
        url = str(args[0] if args else kwargs.get("url"))
        if not url.startswith(OLLAMA):  # Asking the local Ollama for its window is not an external action.
            calls.append(url)
        raise requests.ConnectionError("no network in this test")
    for name in ("get", "post", "put", "delete", "request"):
        monkeypatch.setattr(requests, name, record)
    return calls


@pytest.fixture
def page(web, tmp_path, monkeypatch, outgoing):
    data = tmp_path / "inputs"
    shutil.copytree(FIXTURES, data, ignore=shutil.ignore_patterns("docs"))
    monkeypatch.setenv("SENSAI_CAMPAIGNS_DIR", str(tmp_path / "campaigns"))
    monkeypatch.setenv("SENSAI_EXPORTS_DIR", str(tmp_path / "exports"))
    monkeypatch.setenv("SENSAI_BRAND_FILE", str(data / "brand.json"))
    page = web(client=FakeClient(["Hydrates skin for up to 8 hours."], ["It cures eczema."], ["Noted."]),
               data_dir=str(data))
    page.app.checker = ScriptedChecker()
    return page


def week(page):
    status, events = page.stream({}, path="/api/campaign/weekly-run")
    assert status == 200
    return events


def test_inputs_to_four_outputs_to_private_export_with_nothing_sent(page, tmp_path, outgoing):
    events = week(page)
    assert [(e["name"], e["ok"]) for e in events if e["type"] == "step"] == [
        ("Report", True), ("DM replies", True), ("Posts", True), ("Calendar", True)]
    done = events[-1]
    saved = Path(done["saved"])
    doc = json.loads(saved.read_text(encoding="utf-8"))
    sections, text = doc["sections"], saved.read_text(encoding="utf-8")

    # 1. Grounded post drafts in the creator's voice: approved claims only.
    assert [p["claim_ids"] for p in sections["posts"]["items"]] == [["C01"], ["C03"], []]
    # 2. Unsent replies to anonymized DMs: case keys, never DM ids, contact details or health details.
    assert [r["case_key"] for r in sections["replies"]["items"]] == ["Q1", "Q2"]
    assert not any(s in text for s in ("DM0", "emma@example.com", "Emma", "pregnant"))
    assert sections["replies"]["left_out"] == ["contains name and personal contact details", "contains medical informations"]
    # 3. Weekly report: dated figures computed in code, with their source.
    report = sections["report"]["item"]
    assert (report["period_start"], report["period_end"], report["source"]) == (
        "2026-09-21", "2026-09-27", "instagram_insights_weekly_unique")
    assert (report["accounts_reached"], report["accounts_engaged"], report["engagement_rate"]) == (4200, 630, "15.0%")
    # 4. Proposed calendar: dated entries in the following week, linked to real posts, never published.
    entries = sections["calendar"]["items"]
    assert all("2026-09-28" <= e["date"] <= "2026-10-04" and e["post_id"] in ("P1", "P2", "P3") for e in entries)
    assert all(s["status"] == "draft" for s in sections.values())

    # The chat (B1) works alongside, and the private export needs no approval and no URL.
    assert page.stream({"text": "How long does the serum hydrate?"})[1][-1]["status"] == "completed"
    exported = page.call("POST", "/api/export", {})[1]
    files = exported["conversation"]["files"] + exported["campaign"]["files"]
    assert sorted(Path(f).suffix for f in files) == [".json", ".json", ".md", ".md"]
    assert all(Path(tmp_path / f if not Path(f).is_absolute() else f).exists() for f in files)
    assert "http" not in json.dumps(exported)
    assert outgoing == []  # Nothing was sent, published or shared.


def test_an_approved_section_survives_a_new_run_and_a_change_needs_a_yes(page):
    week(page)
    assert page.call("POST", "/api/campaign/approve", {"section": "posts"})[0] == 200
    before = page.call("GET", "/api/campaign")[1]["sections"]["posts"]
    page.app.checker.posts = posts(("Something else entirely.", []))
    steps = {e["name"]: e for e in week(page) if e["type"] == "step"}
    assert steps["Posts"]["detail"] == "approved, left unchanged"
    assert page.call("GET", "/api/campaign")[1]["sections"]["posts"] == before


def test_privacy_and_unsafe_output_are_surfaced_not_saved(page):
    _, events = page.stream({"text": "Reply to emma@example.com about the serum"})
    assert "[redacted]" in page.client.requests[0][1][-1].content and "emma@" not in page.client.requests[0][1][-1].content
    assert any(e["type"] == "redacted" for e in events)
    _, events = page.stream({"text": "Does it help eczema?"})
    assert any(e["type"] == "blocked" for e in events)  # "It cures eczema." is never shown or kept.
    texts = [i["text"] for i in page.call("GET", "/api/session")[1]["items"]]
    assert "It cures eczema." not in texts and "Does it help eczema?" not in texts


def test_there_is_no_public_share_send_or_publish_route(page, outgoing):
    for path in ("/api/share", "/api/publish", "/api/send"):
        assert page.call("POST", path, {"text": "x"})[0] == 404
    assert "share" not in page.call("GET", "/api/config")[1]["capabilities"]
    assert outgoing == []
