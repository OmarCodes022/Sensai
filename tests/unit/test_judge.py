"""EV1: the judge's schema, and the eval script's planted check, not-judged handling and comparison."""
import importlib.util
import json
from pathlib import Path

import pytest

from sensai.core.errors import LLMConnectionError, LLMError
from sensai.judge import Judgement, Statement, judge

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("ev1_run", ROOT / "evals" / "faithfulness" / "run.py")
run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run)


class FakeJudge:
    def __init__(self, decide):
        self.decide, self.seen = decide, []

    def complete(self, model, messages, schema):
        self.seen.append(messages[1].content)
        result = self.decide(messages[1].content)
        if isinstance(result, BaseException):
            raise result
        return result


def verdict(*labels):
    return Judgement(relevance=5, coherence=5, faithfulness=5 - len([l for l in labels if l != "supported"]),
                     statements=[Statement(text=f"s{i}", label=label) for i, label in enumerate(labels)])


def test_the_judge_sees_question_sources_and_answer_and_lists_flags():
    client = FakeJudge(lambda text: verdict("supported", "contradicted"))
    result = judge(client, "m", "Q?", "", "It cures eczema.")
    assert "(none: no document was retrieved)" in client.seen[0] and "Answer:\nIt cures eczema." in client.seen[0]
    assert [s.label for s in result.flagged()] == ["contradicted"]


def test_scores_outside_1_to_5_are_refused_by_the_schema():
    with pytest.raises(ValueError):
        Judgement(relevance=6, coherence=1, faithfulness=1, statements=[])


def test_an_invalid_verdict_is_not_judged_but_an_unreachable_judge_stops(monkeypatch):
    assert run.judged(FakeJudge(lambda t: LLMError("invalid JSON")), "m", "q", None, "a") == {"judged": False, "error": "invalid JSON"}
    with pytest.raises(LLMConnectionError):
        run.judged(FakeJudge(lambda t: LLMConnectionError("down")), "m", "q", None, "a")


def test_planted_check_counts_misses_and_false_alarms(monkeypatch, capsys):
    # Flags only "cures"; so it misses the 24-hour and ceramides answers, and never raises a false alarm.
    fake = FakeJudge(lambda text: verdict("unsupported") if "cures" in text else verdict("supported"))
    monkeypatch.setattr(run, "OllamaStructuredClient", lambda host, timeout: fake)
    run.planted(type("A", (), {"judge": "m"}))
    assert "Planted check: 1 of 3 wrong answers flagged, 0 false alarm(s) on 3 correct answers (misses ['P5', 'P6']" \
        in capsys.readouterr().out


def test_compare_prints_two_versions_side_by_side(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(run, "HERE", tmp_path)
    (tmp_path / "results").mkdir()
    for label, faithful, flagged in (("v1", 3.6, 5), ("v2", 4.4, 2)):
        (tmp_path / "results" / f"{label}.json").write_text(json.dumps(
            {"label": label, "relevance": 4.2, "coherence": 4.5, "faithfulness": faithful, "flagged": flagged}))
    assert run.compare(["v1", "v2"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[1].split() == ["v1", "4.2", "4.5", "3.6", "5"] and lines[2].split() == ["v2", "4.2", "4.5", "4.4", "2"]
    assert run.compare(["v1", "missing"]) == 1


@pytest.mark.parametrize("text", ["The documents do not cover the price.", "Would you like me to check?",
                                  "We may need to consult the product team.", "The price is not listed in the documents.",
                                  "I'm unable to provide the current prices."])
def test_refusals_questions_and_offers_are_never_flagged(text):
    client = FakeJudge(lambda t: Judgement(relevance=5, coherence=5, faithfulness=1, statements=[
        Statement(text=text, label="unsupported"), Statement(text="It cures eczema", label="contradicted")]))
    assert [s.text for s in judge(client, "m", "q", "", "a").flagged()] == ["It cures eczema"]


def test_faithfulness_comes_from_the_labels_and_a_refusal_is_faithful():
    labels = lambda *ls: FakeJudge(lambda t: Judgement(relevance=3, coherence=3, faithfulness=1, statements=[
        Statement(text=f"claim {i}", label=l) for i, l in enumerate(ls)]))
    assert judge(labels(), "m", "q", "", "The documents do not cover it.").faithfulness == 5
    assert judge(labels("supported", "supported"), "m", "q", "", "a").faithfulness == 5
    assert judge(labels("supported", "contradicted"), "m", "q", "", "a").faithfulness == 3
    assert judge(labels("unsupported"), "m", "q", "", "a").faithfulness == 1
