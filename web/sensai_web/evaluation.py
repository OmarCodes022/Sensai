"""EV1 in the page: check one answer against the brand documents, and list the saved evaluation runs."""
import json
import os

from sensai.core.errors import LLMConnectionError, LLMError
from sensai.judge import judge
from sensai.rag import search_with_hits
from sensai_web.errors import ApiError

RESULTS = os.environ.get("SENSAI_EVALS_DIR", os.path.join("evals", "faithfulness", "results"))
MAX_CHARS = 8_000


def runs() -> list[dict]:
    """Each saved run of evals/faithfulness/run.py: scores, and the statements its judge flagged."""
    if not os.path.isdir(RESULTS):
        return []
    out = []
    for name in sorted(n for n in os.listdir(RESULTS) if n.endswith(".json")):
        try:
            with open(os.path.join(RESULTS, name), encoding="utf-8") as f:
                run = json.load(f)
        except (OSError, ValueError):
            continue
        flagged = [{"n": r["n"], "question": r["question"], **s} for r in run.get("rows", []) if r.get("judged")
                   for s in r.get("flagged", [])]
        out.append({key: run.get(key) for key in ("label", "model", "judge", "search", "questions", "not_judged",
                                                  "relevance", "coherence", "faithfulness")} | {"flagged": flagged})
    return out


def check(app, question: object, answer: object) -> dict:
    """Judge `answer` against what document search finds for `question` (the creator's own text, or a reply)."""
    if not isinstance(question, str) or not isinstance(answer, str) or not question.strip() or not answer.strip():
        raise ApiError(400, "bad_request", "Write the question and the answer to check.")
    if len(question) + len(answer) > MAX_CHARS:
        raise ApiError(413, "too_large", "The question and answer are too long to check.")
    sources = search_with_hits(app.docs, question)[0] if app.docs.enabled and app.docs.ready_count() else ""
    try:
        verdict = judge(app.checker, app.model, question.strip(), sources, answer.strip())
    except LLMConnectionError as exc:
        raise ApiError(503, "ollama_unreachable", str(exc)) from None
    except LLMError as exc:
        raise ApiError(502, "not_judged", f"The judge gave no usable verdict ({exc}). Try again.") from None
    return {**verdict.model_dump(), "flagged": len(verdict.flagged()), "sources": sources}
