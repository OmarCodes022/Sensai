"""EV1: answer the T35 questions like the chat does, have a judge score them, flag what the documents do not back.

    .venv/bin/python evals/faithfulness/run.py --model qwen2.5 --label v1 [--judge qwen2.5] [--search advanced]
    .venv/bin/python evals/faithfulness/run.py --planted --judge qwen2.5     # how far to trust the judge
    .venv/bin/python evals/faithfulness/run.py --compare v1 v2

Needs Ollama with the models and nomic-embed-text. Results go to evals/faithfulness/results/<label>.json.
"""
import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path
from statistics import mean
from time import monotonic

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from sensai.chat.prompts import load_system_prompt  # noqa: E402
from sensai.chat.session import ChatSession  # noqa: E402
from sensai.core.cancellation import CancellationToken  # noqa: E402
from sensai.core.errors import LLMConnectionError, LLMError  # noqa: E402
from sensai.core.ports import ToolResult  # noqa: E402
from sensai.judge import judge  # noqa: E402
from sensai.llm.embeddings import OllamaEmbeddingAdapter  # noqa: E402
from sensai.llm.ollama import OllamaClient  # noqa: E402
from sensai.llm.structured import OllamaStructuredClient  # noqa: E402
from sensai.rag import DOCS_PROMPT, SEARCH_DOCS, DocLibrary, search_with_hits  # noqa: E402
from sensai.rag_advanced import advanced_search, make_ranker  # noqa: E402
from sensai.tools import ToolRegistry, run_with_tools, tool_instructions  # noqa: E402

HERE = Path(__file__).resolve().parent
DOCS = ROOT / "tests" / "fixtures" / "docs"
HOST = "http://localhost:11434"
SCORES = ("relevance", "coherence", "faithfulness")


def answer(model: str, library, search: str, question: str) -> tuple[str, str | None]:
    """(answer, what search_docs returned) through run_with_tools, as in the chat; None if it was not called."""
    ranker = make_ranker(OllamaStructuredClient(HOST, 120), model) if search == "advanced" else None
    found: list[str] = []

    def search_docs(arguments, cancellation=None):
        query = arguments.get("query", "") or ""
        text = advanced_search(library, query, ranker)[0] if ranker else search_with_hits(library, query)[0]
        found.append(text)
        return ToolResult(text)

    registry = ToolRegistry()
    registry.register(SEARCH_DOCS, search_docs, timeout=None)
    system = f"{load_system_prompt(None)}\n\n{DOCS_PROMPT}\n\n{tool_instructions(registry.definitions())}"
    session = ChatSession(OllamaClient(HOST, 120, context_length=8192), model, system)
    text = "".join(run_with_tools(session, registry, question, CancellationToken(monotonic() + 300)))
    return text.strip(), "\n\n".join(found) if found else None


def judged(client, judge_model: str, question: str, sources: str | None, text: str) -> dict:
    try:
        verdict = judge(client, judge_model, question, sources or "", text)
    except LLMConnectionError:
        raise
    except LLMError as exc:  # Invalid JSON or a refused answer: this one is not judged, the run goes on.
        return {"judged": False, "error": str(exc)}
    return {"judged": True, **verdict.model_dump(), "flagged": [s.model_dump() for s in verdict.flagged()]}


def evaluate(args) -> int:
    questions = json.loads((DOCS / "questions.json").read_text(encoding="utf-8"))
    client = OllamaStructuredClient(HOST, 180)
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / "docs"
        shutil.copytree(DOCS, folder)
        (folder / "questions.json").unlink()
        library = DocLibrary(str(folder), OllamaEmbeddingAdapter("nomic-embed-text"), "eval", cache_path=str(Path(tmp) / "c.db"))
        library.sync(wait=True)
        if library.status()["state"] != "ready":
            print("error: the documents were not indexed: is Ollama running, with nomic-embed-text pulled?")
            return 1
        rows = []
        for n, q in enumerate(questions, 1):
            text, sources = answer(args.model, library, args.search, q["question"])
            row = {"n": n, "kind": q["kind"], "question": q["question"], "answer": text, "searched": sources is not None,
                   "sources": sources,
                   **judged(client, args.judge, q["question"], sources, text)}
            rows.append(row)
            print(f"Q{n} [{q['kind']}] {'judged' if row['judged'] else 'not judged'}" +
                  (f": {', '.join(f'{k} {row[k]}' for k in SCORES)}, {len(row['flagged'])} flagged" if row["judged"] else ""))
    done = [r for r in rows if r["judged"]]
    summary = {k: round(mean(r[k] for r in done), 2) if done else None for k in SCORES}
    result = {"label": args.label, "model": args.model, "judge": args.judge, "search": args.search,
              "questions": len(rows), "not_judged": len(rows) - len(done), "not_searched": sum(not r["searched"] for r in rows),
              **summary, "flagged": sum(len(r["flagged"]) for r in done), "rows": rows}
    (HERE / "results").mkdir(exist_ok=True)
    (HERE / "results" / f"{args.label}.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\n{len(rows)} questions   " + "   ".join(f"{k} {summary[k]}" for k in SCORES) +
          f"   not judged {result['not_judged']}   no search {result['not_searched']}")
    flagged = [(r, s) for r in done for s in r["flagged"]]
    print(f"Flagged statements: {len(flagged)}")
    for r, s in flagged:
        print(f"  Q{r['n']} \"{s['text']}\": {s['label']}" + (f" ({s['source']})" if s["source"] else ""))
    print(f"Saved {HERE.relative_to(ROOT) / 'results' / (args.label + '.json')}")
    return 0


def planted(args) -> int:
    client, misses, alarms = OllamaStructuredClient(HOST, 180), [], []
    cases = json.loads((HERE / "planted.json").read_text(encoding="utf-8"))
    for case in cases:
        row = judged(client, args.judge, case["question"], case["sources"], case["answer"])
        caught = row["judged"] and bool(row["flagged"])
        (misses if case["wrong"] and not caught else alarms if not case["wrong"] and caught else []).append(case["id"])
        print(f"{case['id']} {'wrong' if case['wrong'] else 'correct'}: " +
              ("not judged" if not row["judged"] else f"flagged {[s['text'] for s in row['flagged']]}" if caught else "nothing flagged"))
    wrong = sum(c["wrong"] for c in cases)
    print(f"Planted check: {wrong - len(misses)} of {wrong} wrong answers flagged, {len(alarms)} false alarm(s) on "
          f"{len(cases) - wrong} correct answers" + (f" (misses {misses}, false alarms {alarms})" if misses or alarms else ""))
    return 0


def compare(labels: list[str]) -> int:
    rows = []
    for label in labels:
        path = HERE / "results" / f"{label}.json"
        if not path.exists():
            print(f"error: no results for {label} (run with --label {label} first)")
            return 1
        rows.append(json.loads(path.read_text(encoding="utf-8")))
    print(f"{'':<18}{'relevance':>10}{'coherence':>11}{'faithfulness':>14}{'flagged':>9}")
    for r in rows:
        print(f"{r['label']:<18}{r['relevance']!s:>10}{r['coherence']!s:>11}{r['faithfulness']!s:>14}{r['flagged']:>9}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--model", default="qwen2.5", help="the model that answers")
    p.add_argument("--judge", help="the judging model (default: --model)")
    p.add_argument("--label", default="latest", help="name of this version's results")
    p.add_argument("--search", choices=("basic", "advanced"), default="advanced")
    p.add_argument("--planted", action="store_true", help="only check the judge on the planted answers")
    p.add_argument("--compare", nargs=2, metavar=("A", "B"), help="show two saved versions side by side")
    args = p.parse_args(argv)
    args.judge = args.judge or args.model
    if args.compare:
        return compare(args.compare)
    try:
        return planted(args) if args.planted else evaluate(args)
    except LLMConnectionError as exc:
        print(f"error: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
