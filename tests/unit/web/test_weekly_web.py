"""The weekly run in the page: one event per output, the document saved, Stop saves nothing."""
import shutil
from pathlib import Path
from types import SimpleNamespace

from sensai.weekly.outputs import EntryDraft, EntryDrafts, PostDraft, PostDrafts, Reading, Suggestion

FIXTURES = Path(__file__).parents[2] / "fixtures"
ANSWERS = {
    "Reading": Reading(interpretation="A steady week."), "Suggestion": Suggestion(text="It suits dry skin."),
    "PostDrafts": PostDrafts(posts=[PostDraft(caption="Hydrates skin for up to 8 hours.", claim_ids=["C01"]),
                                    PostDraft(caption="Reduces redness in 4 weeks.", claim_ids=["C03"]),
                                    PostDraft(caption="Your evening routine?", claim_ids=[])]),
    "EntryDrafts": EntryDrafts(entries=[EntryDraft(date=f"2026-09-{d}", time="18:00", post_id=f"P{i + 1}", theme="x")
                                        for i, d in enumerate((29, 30))] +
                               [EntryDraft(date="2026-10-01", time="18:00", post_id="P3", theme="x")]),
}


def page_with_inputs(web, tmp_path, monkeypatch, answer=lambda schema: ANSWERS[schema.__name__]):
    data = tmp_path / "inputs"
    shutil.copytree(FIXTURES, data, ignore=shutil.ignore_patterns("docs"))
    monkeypatch.setenv("SENSAI_CAMPAIGNS_DIR", str(tmp_path / "campaigns"))
    page = web(["hi"], data_dir=str(data))
    page.app.checker = SimpleNamespace(complete=lambda model, messages, schema: answer(schema))
    return page


def test_the_page_runs_the_week_and_shows_each_output(web, tmp_path, monkeypatch):
    page = page_with_inputs(web, tmp_path, monkeypatch)
    status, events = page.stream({}, path="/api/campaign/weekly-run")
    assert status == 200 and events[0]["type"] == "start"
    steps = [(e["name"], e["ok"]) for e in events if e["type"] == "step"]
    assert steps == [("Report", True), ("DM replies", True), ("Posts", True), ("Calendar", True)]
    done = events[-1]
    assert done["status"] == "completed" and done["ok"] and done["saved"].endswith("2026-W40.json")
    assert done["doc"]["week"] == "2026-W40" and page.call("GET", "/api/campaign")[1]["week"] == "2026-W40"
    assert page.call("GET", "/api/config")[1]["capabilities"]["weekly_run"] is True


def test_stop_during_the_run_saves_nothing(web, tmp_path, monkeypatch):
    page = None

    def answer(schema):
        page.app.turn.set()  # Stop pressed while the report is being written.
        return ANSWERS[schema.__name__]
    page = page_with_inputs(web, tmp_path, monkeypatch, answer)
    status, events = page.stream({}, path="/api/campaign/weekly-run")
    assert events[-1] == {"type": "done", "status": "stopped", "saved": None}
    assert not (tmp_path / "campaigns" / "2026-W40.json").exists()


def test_a_run_while_a_reply_streams_is_busy(web, tmp_path, monkeypatch):
    page = page_with_inputs(web, tmp_path, monkeypatch)
    page.app.begin_turn()
    assert page.call("POST", "/api/campaign/weekly-run", {})[0] == 429
