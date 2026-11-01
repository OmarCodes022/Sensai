"""EV1 in the page: checking an answer, and the saved runs."""
import json
from types import SimpleNamespace

from sensai.core.errors import LLMConnectionError
from sensai.judge import Judgement, Statement
from sensai_web import evaluation

VERDICT = Judgement(relevance=5, coherence=4, faithfulness=2, statements=[
    Statement(text="It reduces redness in 4 weeks", label="supported", source="calm-barrier-cream"),
    Statement(text="It cures eczema", label="contradicted", source="calm-barrier-cream")])


def test_an_answer_is_judged_and_its_flagged_statements_counted(web):
    page = web(["hi"])
    asked = []
    page.app.checker = SimpleNamespace(complete=lambda model, messages, schema: asked.append(messages) or VERDICT)
    status, body = page.call("POST", "/api/evaluation/check", {"question": "Does it help eczema?", "answer": "It cures eczema."})
    assert status == 200 and body["flagged"] == 1 and body["statements"][1]["label"] == "contradicted"
    assert "Answer:\nIt cures eczema." in asked[0][1].content
    assert page.call("GET", "/api/config")[1]["capabilities"]["evaluation"] is True


def test_bad_input_and_an_unreachable_judge_are_clear(web):
    page = web(["hi"])
    assert page.call("POST", "/api/evaluation/check", {"question": "", "answer": "x"})[0] == 400

    def down(*args):
        raise LLMConnectionError("cannot reach Ollama")
    page.app.checker = SimpleNamespace(complete=down)
    status, body = page.call("POST", "/api/evaluation/check", {"question": "q", "answer": "a"})
    assert status == 503 and body["error"]["code"] == "ollama_unreachable"


def test_saved_runs_are_listed_with_their_flagged_statements(web, tmp_path, monkeypatch):
    monkeypatch.setattr(evaluation, "RESULTS", str(tmp_path))
    (tmp_path / "v1.json").write_text(json.dumps({"label": "v1", "model": "m", "judge": "m", "search": "basic",
        "questions": 1, "not_judged": 0, "relevance": 4.0, "coherence": 5.0, "faithfulness": 3.0,
        "rows": [{"n": 1, "question": "q", "judged": True, "flagged": [{"text": "s", "label": "unsupported", "source": ""}]}]}))
    (tmp_path / "broken.json").write_text("{")
    runs = web(["hi"]).call("GET", "/api/evaluation")[1]["runs"]
    assert [r["label"] for r in runs] == ["v1"] and runs[0]["flagged"] == [
        {"n": 1, "question": "q", "text": "s", "label": "unsupported", "source": ""}]
