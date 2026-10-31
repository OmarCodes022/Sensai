"""Advanced document search: product and version filters, model rerank, threshold and the basic fallback."""
import shutil
from pathlib import Path

import pytest

from fakes import BagOfWordsEmbedding
from sensai.llm.structured import StructuredOutputError
from sensai.rag import DocLibrary
from sensai.rag_advanced import DocSearch, advanced_search, allowed_sources, make_ranker

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "docs"


@pytest.fixture
def library(tmp_path):
    shutil.copytree(FIXTURES, tmp_path / "docs")
    (tmp_path / "docs" / "questions.json").unlink()
    library = DocLibrary(str(tmp_path / "docs"), BagOfWordsEmbedding(), "default", cache_path=str(tmp_path / "s.db"))
    library.sync(wait=True)
    return library


def test_a_named_product_keeps_its_current_sheet_and_general_documents(library):
    keep, described = allowed_sources("Does Calm Barrier Cream soothe skin overnight?", library.metadata())
    assert "calm-barrier-cream" in keep and "faq" in keep
    assert "calm-barrier-cream-2025" not in keep and "hydra-glow-serum" not in keep
    assert described.startswith("product P02")


def test_the_reranker_orders_and_drops_weak_chunks(library):
    def ranker(query, texts):
        return [9 if "redness" in t.lower() else 2 for t in texts]
    text, report = advanced_search(library, "How long does Calm Barrier Cream take to reduce redness?", ranker)
    assert report.reranked and report.kept >= 1 and report.dropped == report.candidates - report.kept
    assert all(h["relevance"] >= 6 and h["source"] != "calm-barrier-cream-2025" for h in report.hits)
    assert "relevance 9/10" in text
    assert report.summary().startswith(f"Kept {report.kept} of {report.candidates} chunks")


def test_nothing_above_the_threshold_says_not_covered(library):
    text, report = advanced_search(library, "What hashtags for Halloween?", lambda q, texts: [1] * len(texts))
    assert report.kept == 0 and "No document covers this question" in text


def test_a_failed_rerank_falls_back_to_the_basic_ranking(library):
    def broken(query, texts):
        raise StructuredOutputError("bad json")
    text, report = advanced_search(library, "Hydra Glow Serum hydration", broken)
    assert not report.reranked and report.kept and "basic ranking used" in report.summary()


def test_make_ranker_checks_the_scores(library):
    class Checker:
        def __init__(self, scores):
            self.scores = scores

        def complete(self, model, messages, schema):
            return schema(scores=[{"passage": p, "score": s} for p, s in self.scores])
    assert make_ranker(Checker([(2, 8), (1, 3)]), "m")("q", ["a", "b"]) == [3, 8]
    assert make_ranker(Checker([(2, 8), (7, 9), (1, 11)]), "m")("q", ["a", "b"]) == [0, 8]  # Missing or bad: 0.
    with pytest.raises(StructuredOutputError):
        make_ranker(Checker([(5, 3)]), "m")("q", ["a", "b"])


def test_the_tool_reports_each_search(library):
    seen = []
    tool = DocSearch(library, lambda q, texts: [8] * len(texts), on_search=seen.append)
    assert tool({"query": "Hydra Glow Serum"}).output.startswith("[hydra-glow-serum")
    assert seen and seen[0] is tool.report
