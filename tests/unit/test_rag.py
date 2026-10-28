"""Brand document search: loading, indexing, the search_docs tool and the /docs and /reindex helpers."""
import shutil
from pathlib import Path

import pytest

from fakes import BagOfWordsEmbedding
from sensai.chat.prompts import load_system_prompt
from sensai.core.errors import LLMConnectionError, ModelNotFoundError
from sensai.llm.embeddings import EmbeddingError
from sensai.memory.vector_index import LocalVectorIndex
from sensai.rag import (DOCS_PROMPT, DocSearch, build_index, chunk_text, docs_command, load_documents,
                        reindex_command, search_docs_handler, superseded_by)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "docs"


@pytest.fixture
def folder(tmp_path):
    shutil.copytree(FIXTURES, tmp_path / "docs")
    return tmp_path / "docs"


def make_search(folder):
    embedding = BagOfWordsEmbedding()
    index = LocalVectorIndex(embedding)
    docs = load_documents(str(folder))
    build_index(docs, embedding, index, "default")
    return DocSearch(index, docs, str(folder), "default", "nomic-embed-text"), embedding


def write(folder, name, text):
    (folder / name).write_text(text, encoding="utf-8")


def test_documents_load_sorted_with_their_header_fields():
    skipped = []
    docs = load_documents(str(FIXTURES), skipped)
    assert [d["source"] for d in docs] == ["brand-voice", "calm-barrier-cream-2025", "calm-barrier-cream", "faq",
                                           "hydra-glow-serum"]  # By file name, the same on every run.
    assert skipped == []  # The folder's README.md is notes, not a document, and is not reported.
    assert "README" not in {d["source"] for d in docs}
    by_source = {d["source"]: d for d in docs}
    assert by_source["calm-barrier-cream"]["product"] == "P02" and by_source["calm-barrier-cream"]["version"] == "2026-09-01"
    assert by_source["faq"]["product"] == "" and by_source["faq"]["title"] == "Serein Studio FAQ"
    assert "Delivery takes 2 or 3 business days" in by_source["faq"]["text"]


def test_a_file_without_a_header_is_skipped_not_half_read(tmp_path):
    write(tmp_path, "notes.md", "Intro text for the notes file\n\n---\n\nsome body\n\n---\n\nmore text here")
    write(tmp_path, "empty.md", "")
    write(tmp_path, "unclosed.md", "---\nsource: x\nversion: 1\n\nno closing line")
    (tmp_path / "binary.md").write_bytes(b"---\nsource: x\n---\n\xff\xfe\x00")
    skipped = []
    assert load_documents(str(tmp_path), skipped) == []
    assert sorted(skipped) == ["binary.md", "empty.md", "notes.md", "unclosed.md"]


def test_header_variants_are_read_correctly(tmp_path):
    write(tmp_path, "a.md", "---\r\nsource: alpha\r\nversion: 2026-01-01\r\n---\r\n\r\nBody of the alpha document\r\n")
    write(tmp_path, "b.md", "---\nsource: beta\n---\n")  # No body at all.
    write(tmp_path, "c.md", "---\ntitle: Gamma\n---\nBody with a --- rule inside\n\n---\n\nand after it\n")
    docs = {d["source"]: d for d in load_documents(str(tmp_path))}
    assert docs["alpha"]["version"] == "2026-01-01" and docs["alpha"]["text"] == "Body of the alpha document"
    assert docs["beta"]["text"] == ""
    assert docs["c"]["title"] == "Gamma" and "and after it" in docs["c"]["text"]  # Source falls back to the file name.


def test_chunks_are_paragraphs_with_some_content():
    assert chunk_text("First paragraph here\n\ntiny\n\n  Second paragraph here  \n\n") == [
        "First paragraph here", "Second paragraph here"]


def test_indexing_counts_chunks_and_a_second_run_replaces_them(folder):
    search, embedding = make_search(folder)
    first = len(search.index.entries("default"))
    assert first > 0
    assert build_index(search.docs, embedding, search.index, "default") == first
    assert len(search.index.entries("default")) == first


def test_a_removed_document_leaves_the_index(folder):
    search, _ = make_search(folder)
    (folder / "faq.md").unlink()
    assert reindex_command(search)[-1].startswith("Reindexed 4 documents")
    assert "faq" not in {e.source for e in search.index.entries("default")}
    assert "faq" not in {d["source"] for d in search.docs}


def test_a_failing_embedding_leaves_the_previous_index_untouched(folder):
    search, embedding = make_search(folder)
    before = [(e.source, e.id) for e in search.index.entries("default")]
    (folder / "faq.md").unlink()
    write(folder, "new.md", "---\nsource: new\nversion: 2026-10-01\n---\n\nA brand new paragraph about price\n")
    embedding.fail = EmbeddingError("Ollama embedding request timed out")
    lines = reindex_command(search)
    assert lines == ["error: Ollama embedding request timed out"]
    assert [(e.source, e.id) for e in search.index.entries("default")] == before
    assert "faq" in {d["source"] for d in search.docs}


def test_a_changed_document_is_found_after_reindex(folder):
    search, _ = make_search(folder)
    write(folder, "faq.md", "---\nsource: faq\ntype: faq\nversion: 2026-10-01\n---\n\nDelivery now takes 1 business day delivery\n")
    assert reindex_command(search) == ["Reindexed 5 documents (%d chunks)." % len(search.index.entries("default"))]
    result = search_docs_handler({"query": "delivery"}, None, index=search.index, creator_id="default", docs_meta=search.docs)
    assert "1 business day" in result.output and "[faq, 2026-10-01]" in result.output


def test_reindex_warns_about_files_it_skipped(folder):
    write(folder, "draft.md", "Just notes, no header")
    lines = reindex_command(make_search(folder)[0])
    assert lines[0] == "warning: skipped draft.md: no header between --- lines"
    assert lines[1].startswith("Reindexed")


def test_an_old_version_is_marked_outdated_and_the_current_one_is_not(folder):
    search, _ = make_search(folder)
    docs = {d["source"]: d for d in search.docs}
    assert superseded_by(docs["calm-barrier-cream-2025"], search.docs)["source"] == "calm-barrier-cream"
    assert superseded_by(docs["calm-barrier-cream"], search.docs) is None
    assert superseded_by(docs["faq"], search.docs) is None  # No product: never compared.
    result = search_docs_handler({"query": "cream"}, None, index=search.index, creator_id="default", docs_meta=search.docs)
    lines = result.output.splitlines()
    old = [line for line in lines if line.startswith("[calm-barrier-cream-2025")]
    assert old and "OUTDATED: superseded by calm-barrier-cream 2026-09-01" in old[0]
    assert not any("OUTDATED" in line for line in lines if line.startswith("[calm-barrier-cream,"))


def test_the_tool_reports_when_nothing_is_indexed():
    index = LocalVectorIndex(BagOfWordsEmbedding())
    assert search_docs_handler({"query": "anything"}, None, index=index, creator_id="default", docs_meta=[]).output == \
        "No relevant documents found"


def test_docs_lists_documents_with_version_and_chunk_count(folder):
    search, _ = make_search(folder)
    lines = docs_command(search)
    assert lines == sorted(lines) and len(lines) == 5
    assert any(line.startswith("faq   2026-09-01   ") and line.endswith(" chunks") for line in lines)
    assert docs_command(search, "   ") == lines  # A blank argument is the same as no argument.


def test_docs_with_text_shows_scored_hits_without_asking_the_model(folder):
    search, _ = make_search(folder)
    lines = docs_command(search, "delivery")
    assert lines[0].startswith("[1] faq · score ") and "Delivery takes 2 or 3 business days" in lines[0]
    assert len(lines) <= 3


@pytest.mark.parametrize("error, expected", [
    (ModelNotFoundError("Ollama embedding model not found"), "error: Ollama embedding model not found (try: ollama pull nomic-embed-text)"),
    (LLMConnectionError("cannot reach Ollama for embeddings"), "error: cannot reach Ollama for embeddings"),
    (EmbeddingError("Ollama embedding request failed"), "error: Ollama embedding request failed"),
])
def test_search_failures_are_reported_as_lines_not_raised(folder, error, expected):
    search, embedding = make_search(folder)
    embedding.fail = error
    assert docs_command(search, "delivery") == [expected]
    assert reindex_command(search)[-1] == expected


def test_the_document_search_prompt_is_not_part_of_the_default_prompt():
    assert "search_docs" not in load_system_prompt() and "search_docs" in DOCS_PROMPT
    assert "OUTDATED" in DOCS_PROMPT
