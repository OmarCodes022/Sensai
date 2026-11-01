"""A4 in the page: the dated versions, using one (rollback), and comparing two on the same questions."""
from sensai_web import prompts


def versions(tmp_path, monkeypatch):
    folder = tmp_path / "versions"
    folder.mkdir()
    (folder / "2026-10-20-original.txt").write_text("Be brief.")
    (folder / "2026-11-01-warm.txt").write_text("Be warm.")
    (tmp_path / "questions.txt").write_text("# comment\nFirst question?\nSecond question?\n")
    monkeypatch.setattr(prompts, "FOLDER", str(folder))
    monkeypatch.setattr(prompts, "REPORTS", str(tmp_path / "reports"))


def test_versions_are_listed_and_one_can_be_used_then_undone(web, tmp_path, monkeypatch):
    versions(tmp_path, monkeypatch)
    page = web(["ok"])
    listed = page.call("GET", "/api/prompts")[1]
    assert [v["name"] for v in listed["items"]] == ["2026-10-20-original.txt", "2026-11-01-warm.txt"] and listed["active"] is None
    assert page.call("POST", "/api/prompts/use", {"name": "2026-10-20-original.txt"})[1]["active"] == "2026-10-20-original.txt"
    page.stream({"text": "hi"})
    sent = page.client.requests[-1][1]
    assert sent[0].content.startswith("Be brief.") and [m.role for m in sent].count("system") == 1
    assert page.call("POST", "/api/prompts/use", {"name": None})[1]["active"] is None
    assert not page.app.active.session.messages[0].content.startswith("Be brief.")
    assert page.call("POST", "/api/prompts/use", {"name": "nope.txt"})[0] == 404


def test_two_versions_answer_the_same_questions_and_a_report_is_written(web, tmp_path, monkeypatch):
    versions(tmp_path, monkeypatch)
    page = web(["A1"], ["B1"], ["A2"], ["B2"])
    _, events = page.stream({"a": "2026-10-20-original.txt", "b": "2026-11-01-warm.txt"}, path="/api/prompts/compare")
    answers = [(e["n"], e["label"], e["text"]) for e in events if e["type"] == "answer"]
    assert answers == [(1, "A", "A1"), (1, "B", "B1"), (2, "A", "A2"), (2, "B", "B2")]
    assert [r[1][0].content for r in page.client.requests] == ["Be brief.", "Be warm.", "Be brief.", "Be warm."]
    report = events[-1]["report"]
    text = open(report, encoding="utf-8").read()
    assert "First question?" in text and "B2" in text and "2026-11-01-warm.txt" in text
    assert page.call("POST", "/api/prompts/compare", {"a": "x", "b": "y"})[0] == 404
    assert page.call("GET", "/api/config")[1]["capabilities"]["prompt_versions"] is True
