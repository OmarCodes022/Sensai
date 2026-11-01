"""The weekly run (T45) on tests/fixtures, with a scripted model: four outputs, each checked and failing alone."""
import json
import shutil
from pathlib import Path

import pytest

from sensai.campaign import CampaignStore, approve
from sensai.core.errors import LLMError
from sensai.weekly.outputs import EntryDraft, EntryDrafts, PostDraft, PostDrafts, Reading, Suggestion, _time
from sensai.weekly.run import run_week

FIXTURES = Path(__file__).parents[2] / "fixtures"
POSTS = PostDrafts(posts=[
    PostDraft(caption="Hydrates skin for up to 8 hours. Ready for Monday?", claim_ids=["C01"]),
    PostDraft(caption="Reduces redness in 4 weeks. Gentle every night.", claim_ids=["Reduces redness in 4 weeks"]),
    PostDraft(caption="What is your evening routine?", claim_ids=[]),
    PostDraft(caption="It cures eczema!", claim_ids=["C02"]),  # Refused by the guardrails.
])
CALENDAR = EntryDrafts(entries=[EntryDraft(date="2026-09-29", time="6:30 pm", post_id="P1", theme="Launch"),
                                EntryDraft(date="2026-09-30", time="10:00 AM", post_id="P2", theme="Calm"),
                                EntryDraft(date="2026-10-02", time="12:00", post_id="P3", theme="Question"),
                                EntryDraft(date="2026-12-25", time="12:00", post_id="P3", theme="Outside the week")])


def scripted(**answers):
    """ask() answering by schema name; a list is consumed in order, an exception is raised."""
    requests = []

    def ask(instructions, request, schema):
        requests.append((schema.__name__, request))
        answer = answers[schema.__name__]
        if isinstance(answer, list):
            answer = answer.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer
    ask.requests = requests
    return ask


def model(**overrides):
    return scripted(**{"Reading": Reading(interpretation="A steady week."), "PostDrafts": POSTS,
                       "EntryDrafts": CALENDAR, "Suggestion": Suggestion(text="Yes, it suits dry skin."), **overrides})


@pytest.fixture
def folder(tmp_path):
    copy = tmp_path / "inputs"
    shutil.copytree(FIXTURES, copy, ignore=shutil.ignore_patterns("docs"))
    return copy


@pytest.fixture
def store(tmp_path):
    return CampaignStore(str(tmp_path / "campaigns"))


def saved(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def test_the_four_outputs_are_prepared_checked_and_saved(folder, store):
    ask = model()
    header, outcomes, path = run_week(str(folder), store, ask)
    assert [(o.name, o.ok) for o in outcomes] == [("Report", True), ("DM replies", True), ("Posts", True), ("Calendar", True)]
    assert header == "Report week 2026-09-21 to 2026-09-27 · calendar for 2026-09-28 to 2026-10-04"
    doc = saved(path)["sections"]
    report = doc["report"]["item"]
    assert (report["accounts_reached"], report["accounts_engaged"], report["engagement_rate"]) == (4200, 630, "15.0%")
    assert [r["case_key"] for r in doc["replies"]["items"]] == ["Q1", "Q2"] and doc["replies"]["eligible"] == 2
    assert doc["replies"]["left_out"] == ["contains name and personal contact details", "contains medical informations"]
    text = Path(path).read_text(encoding="utf-8")
    assert "emma" not in text.lower() and "pregnant" not in text and "DM0" not in text  # Never read, never stored.
    assert [p["claim_ids"] for p in doc["posts"]["items"]] == [["C01"], ["C03"], []]  # Wording mapped back to its id.
    assert "cures" not in text and "1 left out" in outcomes[2].detail
    entries = doc["calendar"]["items"]
    assert [(e["date"], e["time"], e["post_id"]) for e in entries] == [
        ("2026-09-29", "18:30", "P1"), ("2026-09-30", "10:00", "P2"), ("2026-10-02", "12:00", "P3")]


def test_a_missing_engagement_file_fails_only_the_report(folder, store):
    from datetime import timedelta
    from sensai.campaign.document import coming_week
    (folder / "engagement.csv").unlink()
    _, monday, _ = coming_week()  # No report week: the calendar is for the coming week.
    entries = [EntryDraft(date=(monday + timedelta(days=i)).isoformat(), time="12:00", post_id=f"P{i + 1}", theme="x")
               for i in range(3)]
    _, outcomes, path = run_week(str(folder), store, model(EntryDrafts=EntryDrafts(entries=entries)))
    assert [(o.name, o.ok) for o in outcomes] == [("Report", False), ("DM replies", True), ("Posts", True), ("Calendar", True)]
    assert outcomes[0].detail == "engagement.csv is missing" and saved(path)["sections"]["report"]["item"] is None


def test_zero_reach_shows_no_rate(folder, store):
    csv = folder / "engagement.csv"
    csv.write_text(csv.read_text(encoding="utf-8").replace(",4200,630,15.0,", ",0,0,n/a,"), encoding="utf-8")
    _, outcomes, path = run_week(str(folder), store, model())
    assert saved(path)["sections"]["report"]["item"]["engagement_rate"] == "n/a (zero reach)"
    assert "rate n/a (zero reach)" in outcomes[0].detail


def test_engaged_above_reached_fails_the_report(folder, store):
    csv = folder / "engagement.csv"
    csv.write_text(csv.read_text(encoding="utf-8").replace(",4200,630,", ",10,630,"), encoding="utf-8")
    _, outcomes, _ = run_week(str(folder), store, model())
    assert not outcomes[0].ok and "630 engaged out of 10 reached" in outcomes[0].detail


def test_a_missing_brand_file_fails_replies_and_posts(folder, store):
    (folder / "brand.json").unlink()
    _, outcomes, _ = run_week(str(folder), store, model())
    assert [(o.name, o.ok) for o in outcomes] == [("Report", True), ("DM replies", False), ("Posts", False), ("Calendar", False)]
    assert outcomes[1].detail == "brand.json is missing"


def test_a_refused_reply_is_rewritten_once_then_left_out(folder, store):
    ask = model(Suggestion=[Suggestion(text="It cures dryness."), Suggestion(text="It suits dry skin."),
                            Suggestion(text="It cures acne."), Suggestion(text="It heals acne.")])
    _, outcomes, path = run_week(str(folder), store, ask)
    doc = saved(path)["sections"]["replies"]
    assert [r["suggestion"] for r in doc["items"]] == ["It suits dry skin."]
    assert doc["left_out"][-1].startswith("reply refused:") and "Rewrite it" in ask.requests[2][1]


def test_too_few_posts_fail_and_leave_the_calendar_without_posts(folder, store):
    few = PostDrafts(posts=[PostDraft(caption="Hello", claim_ids=[])])
    _, outcomes, _ = run_week(str(folder), store, model(PostDrafts=[few, few]))
    assert not outcomes[2].ok and "at least 3" in outcomes[2].detail
    assert outcomes[3].detail == "no posts to schedule"


def test_a_model_failure_fails_only_its_output(folder, store):
    _, outcomes, _ = run_week(str(folder), store, model(EntryDrafts=LLMError("connection refused")))
    assert [o.ok for o in outcomes] == [True, True, True, False]
    assert outcomes[3].detail == "the model failed: connection refused"


def test_approved_sections_are_left_unchanged(folder, store):
    _, _, path = run_week(str(folder), store, model())
    doc = store.load("2026-W40")
    approve(store, doc, "posts")
    before = saved(path)["sections"]["posts"]
    _, outcomes, _ = run_week(str(folder), store, model(PostDrafts=PostDrafts(posts=[])))
    assert outcomes[2].detail == "approved, left unchanged" and saved(path)["sections"]["posts"] == before


def test_ctrl_c_saves_nothing_and_keeps_the_earlier_file(folder, store):
    _, _, path = run_week(str(folder), store, model())
    before = Path(path).read_bytes()
    with pytest.raises(KeyboardInterrupt):
        run_week(str(folder), store, model(EntryDrafts=KeyboardInterrupt()))
    assert Path(path).read_bytes() == before


@pytest.mark.parametrize("given, expected", [("10:00 AM", "10:00"), ("6:30 pm", "18:30"), ("12:15 AM", "00:15"),
                                             ("18h00", "18:00"), ("noon", "noon")])
def test_times_are_read_as_hh_mm(given, expected):
    assert _time(given) == expected
