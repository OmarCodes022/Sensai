"""EV3 in the page: each turn is logged with its tools, and /api/stats feeds the Insights page."""
from sensai import usage_log


def test_a_turn_is_logged_and_the_stats_show_it(web, tmp_path, monkeypatch):
    page = web(['{"tool": "calculate", "arguments": {"expression": "630 / 4200 * 100"}}'], ["15%."])
    monkeypatch.setattr(usage_log, "_path", str(tmp_path / "log.jsonl"))
    page.app.log_path = str(tmp_path / "log.jsonl")
    page.stream({"text": "engagement rate?"})
    s = page.call("GET", "/api/stats")[1]
    assert s["calls"] >= 1 and s["tools"]["calculate"] == {"calls": 1, "failed": 0}
    chat = next(r for r in s["recent"] if r["kind"] == "chat")
    assert chat["question"] == "engagement rate?" and chat["error"] is None
    assert page.call("GET", "/api/config")[1]["capabilities"]["stats"] is True
