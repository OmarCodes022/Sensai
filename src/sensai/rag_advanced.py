"""Advanced document search (R2): filter by product and current version, rerank with the model, drop weak matches.

Basic search (rag.search_with_hits) always returns the closest chunks; this keeps only chunks of
the product the question names (plus general documents), from each product's newest sheet, then
asks the model to score them and drops those below the threshold. A failed rerank falls back to
the basic ranking for that search.
"""
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from sensai.core.errors import LLMError
from sensai.core.messages import Message
from sensai.core.ports import ToolResult
from sensai.llm.structured import StructuredOutputError
from sensai.rag import DocLibrary, superseded_by

CANDIDATES = 10
KEEP = 3
THRESHOLD = 6
POOL = 50  # The index has no filter: search wide, then filter.
RANK_PROMPT = ("Score how well each numbered passage answers the question, from 0 (unrelated) to 10 (answers it "
               "directly). Return one {passage, score} entry per passage.")


class Score(BaseModel):
    passage: int = Field(description="the passage number")
    score: int = Field(description="0 (unrelated) to 10 (answers it directly)")


class Scores(BaseModel):
    scores: list[Score]


@dataclass
class Report:
    filter: str
    candidates: int = 0
    kept: int = 0
    reranked: bool = False
    warning: str = ""
    hits: list[dict] = field(default_factory=list)

    @property
    def dropped(self) -> int:
        return self.candidates - self.kept

    def summary(self) -> str:
        if not self.reranked:
            return f"Kept {self.kept} of {self.candidates} chunks ({self.warning or 'basic ranking'})"
        return f"Kept {self.kept} of {self.candidates} chunks ({self.dropped} below {THRESHOLD}/10 dropped)"


def _named(query: str, docs: list[dict]) -> set[str]:
    """Products the question names, by their sheet's title or source name."""
    low = query.lower()
    return {d["product"] for d in docs if d.get("product") and
            (d["title"].lower() in low or d["source"].replace("-", " ").lower() in low
             or " ".join(d["title"].lower().split()[:2]) in low)}  # "Calm Barrier" names Calm Barrier Cream.


def allowed_sources(query: str, docs: list[dict]) -> tuple[set[str], str]:
    """(sources to keep, a short description of the filter)."""
    current = [d for d in docs if superseded_by(d, docs) is None]
    products = _named(query, docs)
    keep = {d["source"] for d in current if not products or not d.get("product") or d["product"] in products}
    described = f"product {', '.join(sorted(products))}, " if products else ""
    return keep, described + "newest product sheets only"


def make_ranker(checker, model: str):
    """A ranker(query, texts) -> scores built on the structured client."""
    def rank(query: str, texts: list[str]) -> list[int]:
        passages = "\n\n".join(f"[{n}] {text}" for n, text in enumerate(texts, 1))
        result = checker.complete(model, [Message(role="system", content=RANK_PROMPT),
                                          Message(role="user", content=f"Question: {query}\n\nPassages:\n{passages}")], Scores)
        given = {s.passage: s.score for s in result.scores if 1 <= s.passage <= len(texts) and 0 <= s.score <= 10}
        if not given:
            raise StructuredOutputError("no usable score for the passages")
        return [given.get(n, 0) for n in range(1, len(texts) + 1)]  # A passage left out counts as unrelated.
    return rank


def advanced_search(library: DocLibrary, query: str, ranker=None) -> tuple[str, Report]:
    """The tool's answer text and a report (filter, kept/dropped, hits with relevance)."""
    docs = library.metadata()
    keep, described = allowed_sources(query, docs)
    report = Report(described)
    found = [hit for hit in library.search(query, POOL) if hit.source in keep][:CANDIDATES]
    report.candidates = len(found)
    if not found:
        return "No document covers this question. Say so; do not guess.", report
    scores = None
    if ranker is not None:
        try:
            scores = ranker(query, [hit.text for hit in found])
            report.reranked = True
        except (StructuredOutputError, LLMError, ValueError) as exc:
            report.warning = f"rerank unavailable, basic ranking used: {type(exc).__name__}"
    if scores is None:
        chosen = [(hit, None) for hit in found[:KEEP]]
    else:
        ranked = sorted(zip(found, scores), key=lambda pair: -pair[1])
        chosen = [(hit, s) for hit, s in ranked if s >= THRESHOLD][:KEEP]
    report.kept = len(chosen)
    if not chosen:
        return "No document covers this question (every passage scored below the threshold). Say so; do not guess.", report
    by_source = {d["source"]: d for d in docs}
    lines = []
    for n, (hit, score) in enumerate(chosen, 1):
        version = by_source.get(hit.source, {}).get("version", "")
        relevance = f", relevance {score}/10" if score is not None else ""
        lines.append(f"[{hit.source}, {version}{relevance}] {hit.text}")
        report.hits.append({"n": n, "source": hit.source, "version": version, "score": round(hit.score, 3),
                            "relevance": score, "outdated": False, "text": hit.text})
    return "\n".join(lines), report


class DocSearch:
    """The search_docs tool in advanced mode; keeps the last report for the source list."""

    def __init__(self, library: DocLibrary, ranker=None, on_search=None):
        self.library, self.ranker, self.on_search = library, ranker, on_search
        self.report: Report | None = None

    def __call__(self, arguments, cancellation=None) -> ToolResult:
        text, self.report = advanced_search(self.library, arguments.get("query", "") or "", self.ranker)
        if self.on_search:
            self.on_search(self.report)
        return ToolResult(text)
