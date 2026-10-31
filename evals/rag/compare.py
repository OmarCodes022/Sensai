"""Basic vs advanced document search on the T35 questions (search only, no answers).

    .venv/bin/python evals/rag/compare.py [model]     # default qwen2.5; needs Ollama and nomic-embed-text

Per question kind it prints: how often the expected source is kept (direct), how many chunks of the
wrong product (near-miss) or the outdated sheet (outdated) are kept, and how many unsupported
questions end with no chunk at all.
"""
import json
import shutil
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from sensai.core.errors import LLMError  # noqa: E402
from sensai.llm.embeddings import OllamaEmbeddingAdapter  # noqa: E402
from sensai.llm.structured import OllamaStructuredClient  # noqa: E402
from sensai.rag import DocLibrary  # noqa: E402
from sensai.rag_advanced import advanced_search, make_ranker  # noqa: E402

DOCS = ROOT / "tests" / "fixtures" / "docs"


def product_of(source, docs):
    return next((d["product"] for d in docs if d["source"] == source), "")


def score(question, kept, docs):
    """The measure for this question's kind, from the sources a search kept."""
    kind, expected = question["kind"], question["source"]
    if kind == "direct":
        return int(expected in kept)
    if kind == "near-miss":  # The question names the other product: its chunks are the wrong ones.
        asked = {d["product"] for d in docs if d.get("product") and " ".join(d["title"].lower().split()[:2]) in question["question"].lower()}
        return sum(1 for s in kept if product_of(s, docs) and product_of(s, docs) not in asked)
    if kind == "outdated":
        return sum(1 for s in kept if s == expected)
    return int(not kept)  # unsupported: 1 when nothing was kept


LABEL = {"direct": "expected source kept", "near-miss": "wrong-product chunks kept",
         "outdated": "outdated chunks kept", "unsupported": "ended with no chunks"}


def main(model: str = "qwen2.5") -> int:
    questions = json.loads((DOCS / "questions.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / "docs"
        shutil.copytree(DOCS, folder)
        (folder / "questions.json").unlink()
        library = DocLibrary(str(folder), OllamaEmbeddingAdapter("nomic-embed-text"), "eval", cache_path=str(Path(tmp) / "c.db"))
        library.sync(wait=True)
        if library.status()["state"] != "ready":
            print(f"error: documents not indexed ({library.status().get('error') or 'is Ollama running with nomic-embed-text?'})")
            return 1
        ranker = make_ranker(OllamaStructuredClient("http://localhost:11434", 120), model)
        docs = library.metadata()
        totals = {mode: defaultdict(int) for mode in ("basic", "advanced")}
        counts = defaultdict(int)
        try:
            for q in questions:
                counts[q["kind"]] += 1
                basic = [hit.source for hit in library.search(q["question"], 3)]
                _, report = advanced_search(library, q["question"], ranker)
                advanced = [h["source"] for h in report.hits]
                totals["basic"][q["kind"]] += score(q, basic, docs)
                totals["advanced"][q["kind"]] += score(q, advanced, docs)
                print(f"- [{q['kind']}] {q['question']}\n    basic: {basic}\n    advanced: {advanced} ({report.summary()})")
        except LLMError as exc:
            print(f"error: Ollama failed during the comparison: {exc}")
            return 1
    print(f"\nModel for the rerank: {model}")
    print(f"{'kind':<12} {'measure':<28} {'basic':>6} {'advanced':>9}")
    for kind in ("direct", "near-miss", "outdated", "unsupported"):
        if counts[kind]:
            print(f"{kind:<12} {LABEL[kind]:<28} {totals['basic'][kind]:>6} {totals['advanced'][kind]:>9}   (of {counts[kind]} question(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:2]))
