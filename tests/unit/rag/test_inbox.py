"""Customer DMs in document search: only privacy-safe questions, redacted, never in the Python sandbox."""
import json
import shutil
from pathlib import Path

from fakes import BagOfWordsEmbedding
from sensai.guardrails import load_guardrail
from sensai.rag.basic import DocLibrary, search_with_hits
from sensai.rag.inbox import inbox_document
from sensai.tools.sandbox import data_file_names

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
DMS = {"dms": [
    {"id": "DM01", "question": "Does the serum work on dry skin?", "eligible": True, "privacy_safe": True},
    {"id": "DM02", "question": "I'm Emma, emma@example.com, will this help my eczema?", "eligible": False,
     "privacy_safe": False, "rejection_reason": "contains name and personal contact details"},
    {"id": "DM05", "question": "Can I order a refill? Call me on 06 12 34 56 78", "eligible": True, "privacy_safe": True},
]}


def inbox(tmp_path):
    path = tmp_path / "dms.json"
    path.write_text(json.dumps(DMS), encoding="utf-8")
    return path


def test_only_privacy_safe_questions_are_kept_redacted_and_without_ids(tmp_path):
    text = inbox_document(str(inbox(tmp_path)), load_guardrail(None, None))
    assert "Customer questions received by DM (privacy-filtered):\n- Does the serum work on dry skin?" in text
    assert "Emma" not in text and "emma@example.com" not in text and "eczema" not in text  # Flagged: never read.
    assert "06 12 34 56 78" not in text and "refill" in text  # Kept, with the phone redacted.
    assert "DM01" not in text and "DM05" not in text


def test_the_dms_are_searchable_next_to_the_documents(tmp_path):
    shutil.copytree(FIXTURES / "docs", tmp_path / "docs")
    library = DocLibrary(str(tmp_path / "docs"), BagOfWordsEmbedding(), "default", cache_path=str(tmp_path / "s.db"))
    library.add_inbox(str(inbox(tmp_path)), load_guardrail(None, None))
    library.sync(wait=True)
    text, hits = search_with_hits(library, "customer question serum dry skin")
    assert any(h["source"] == "customer-dms" for h in hits) and "Does the serum work on dry skin?" in text
    assert "emma" not in text.lower()


def test_a_missing_or_broken_inbox_indexes_nothing(tmp_path):
    (tmp_path / "dms.json").write_text("{not json", encoding="utf-8")
    assert inbox_document(str(tmp_path / "dms.json"), load_guardrail(None, None)).endswith("---\n\n")
    assert inbox_document(str(tmp_path / "none.json"), load_guardrail(None, None)).endswith("---\n\n")


def test_the_raw_dms_never_reach_the_python_sandbox(tmp_path):
    inbox(tmp_path)
    (tmp_path / "engagement.csv").write_text("date,reach\n", encoding="utf-8")
    assert data_file_names(str(tmp_path)) == ["engagement.csv"]


def test_questions_come_in_blocks_of_ten_so_a_short_inbox_is_one_result(tmp_path):
    many = {"dms": [{"question": f"Question number {n} about the serum?", "eligible": True, "privacy_safe": True}
                    for n in range(12)]}
    (tmp_path / "dms.json").write_text(json.dumps(many), encoding="utf-8")
    text = inbox_document(str(tmp_path / "dms.json"), load_guardrail(None, None))
    parts = text.split("---\n\n", 1)[1].split("\n\n")
    assert [p.count("\n- ") for p in parts[:2]] == [10, 2]
    assert parts[2:] == [f"Customer question received by DM: Question number {n} about the serum?" for n in range(12)]


def test_the_inbox_preview_shows_what_is_indexed_not_the_raw_file(tmp_path):
    shutil.copytree(FIXTURES / "docs", tmp_path / "docs")
    library = DocLibrary(str(tmp_path / "docs"), BagOfWordsEmbedding(), "default", cache_path=str(tmp_path / "s.db"))
    library.add_inbox(str(inbox(tmp_path)), load_guardrail(None, None))
    library.sync(wait=True)
    shown = library.read("dms.json")
    assert shown["source"] == "customer-dms" and "Does the serum work on dry skin?" in shown["text"]
    assert "emma" not in shown["text"].lower() and "DM01" not in shown["text"]
