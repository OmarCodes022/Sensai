"""DocLibrary: a folder that indexes itself, the search_docs tool, and the slash command helpers."""
import os
import shutil
import threading
from pathlib import Path

import pytest

from fakes import BagOfWordsEmbedding
from sensai.chat.prompts import load_system_prompt
from sensai.core.errors import LLMConnectionError, ModelNotFoundError
from sensai.llm.embeddings import EmbeddingError
from sensai import rag
from sensai.rag import (DOCS_PROMPT, DocError, DocLibrary, add_command, docs_command, reindex_command,
                        remove_command, search_docs_handler)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "docs"


@pytest.fixture
def folder(tmp_path):
    shutil.copytree(FIXTURES, tmp_path / "docs")
    (tmp_path / "docs" / "questions.json").write_text("[]")  # Not a document type.
    return tmp_path / "docs"


def make(folder, tmp_path, embedding=None, **kwargs):
    embedding = embedding or BagOfWordsEmbedding()
    library = DocLibrary(str(folder), embedding, "default", cache_path=str(tmp_path / "s.db"), **kwargs)
    library.sync(wait=True)
    return library, embedding


def write(folder, name, text, header=True):
    body = f"---\nsource: {name.rsplit('.', 1)[0]}\nversion: 2026-10-01\n---\n\n{text}\n" if header else text
    (folder / name).write_text(body, encoding="utf-8")


def sources(library):
    return {e.source for e in library.index.entries("default")}


def test_a_folder_is_indexed_at_startup_without_any_command(folder, tmp_path):
    library, _ = make(folder, tmp_path)
    assert library.status()["state"] == "ready" and library.ready_count() == 5
    assert sources(library) == {"brand-voice", "calm-barrier-cream", "calm-barrier-cream-2025", "faq", "hydra-glow-serum"}
    assert [d["name"] for d in library.documents()][:2] == ["brand-voice.md", "calm-barrier-cream-2025.md"]
    assert all(d["state"] == "ready" and d["chunks"] > 0 for d in library.documents())


def test_a_file_dropped_into_the_folder_is_found_after_a_sync(folder, tmp_path):
    library, _ = make(folder, tmp_path)
    write(folder, "shipping.md", "Shipping to Canada takes 9 days delivery", header=False)
    assert library.status()["state"] == "indexing" and library.status()["pending"] == 1
    library.sync(wait=True)
    assert library.status()["state"] == "ready" and "shipping" in sources(library)
    assert "9 days" in library.search("delivery")[0].text


def test_an_edited_file_is_indexed_again_and_a_deleted_one_leaves(folder, tmp_path):
    library, _ = make(folder, tmp_path)
    write(folder, "faq.md", "Delivery now takes 1 business day delivery")
    (folder / "hydra-glow-serum.md").unlink()
    library.sync(wait=True)
    assert "hydra-glow-serum" not in sources(library) and library.ready_count() == 4
    assert "1 business day" in library.search("delivery")[0].text


def test_files_without_a_header_are_still_documents(folder, tmp_path):
    (folder / "notes.txt").write_text("Intro text for the notes\n\n---\n\nsome body about price\n\n---\n\nmore", encoding="utf-8")
    library, _ = make(folder, tmp_path)
    doc = next(d for d in library.metadata() if d["file"] == "notes.txt")
    assert (doc["source"], doc["title"], doc["product"]) == ("notes", "notes", "")
    assert len(doc["version"]) == 10 and doc["text"].count("---") == 2  # The whole file, nothing half read.


def test_the_header_is_read_only_at_the_start_of_the_file(folder, tmp_path):
    (folder / "late.md").write_text("Intro paragraph here\n\n---\nsource: nope\n---\n\nbody text here", encoding="utf-8")
    library, _ = make(folder, tmp_path)
    assert next(d for d in library.metadata() if d["file"] == "late.md")["source"] == "late"


def test_readme_and_other_types_and_hidden_files_are_ignored(folder, tmp_path):
    (folder / ".hidden.md").write_text("hidden text here", encoding="utf-8")
    (folder / "data.csv").write_text("a,b", encoding="utf-8")
    library, _ = make(folder, tmp_path)
    assert library.ready_count() == 5 and "README" not in sources(library)


def test_an_unreadable_file_is_skipped_once_and_not_retried(folder, tmp_path):
    (folder / "binary.md").write_bytes(b"\xff\xfe\x00broken")
    library, embedding = make(folder, tmp_path)
    assert library.notices().count("warning: skipped binary.md: not readable UTF-8 text") == 1
    calls = embedding.calls
    library.sync(wait=True)
    assert embedding.calls == calls and library.status()["state"] == "ready"


def test_two_files_with_the_same_source_both_stay_searchable(folder, tmp_path):
    (folder / "faq-copy.md").write_text("---\nsource: faq\nversion: 2026-10-02\n---\n\nA copy about delivery delivery", encoding="utf-8")
    library, _ = make(folder, tmp_path)
    assert len(sources(library)) == 6 and library.ready_count() == 6 and "faq-faq" in sources(library)


def test_the_vector_cache_makes_a_restart_free_and_edits_cheap(folder, tmp_path):
    first, embedding = make(folder, tmp_path)
    assert embedding.calls > 0
    second, again = make(folder, tmp_path)
    assert again.calls == 0 and second.ready_count() == 5  # Same text, same model: no embedding call.
    write(folder, "faq.md", "A brand new paragraph about price")
    third_embedding = BagOfWordsEmbedding()
    third, _ = make(folder, tmp_path, third_embedding)
    assert 0 < third_embedding.calls <= 2  # Only the changed file's chunks.


def test_a_different_embedding_model_does_not_reuse_the_cache(folder, tmp_path):
    make(folder, tmp_path, model="nomic-embed-text")
    other = BagOfWordsEmbedding()
    make(folder, tmp_path, other, model="other-model")
    assert other.calls > 0


def test_a_failing_embedding_model_switches_search_off_but_keeps_the_old_index(folder, tmp_path, monkeypatch):
    library, embedding = make(folder, tmp_path)
    library.notices()  # The startup message.
    before = sources(library)
    write(folder, "new.md", "A new paragraph about price")
    embedding.fail = ModelNotFoundError("Ollama embedding model not found")
    library.sync(wait=True)
    status = library.status()
    assert status["state"] == "unavailable" and "ollama pull" in status["error"]
    assert library.notices() == [f"Document search is off: {status['error']}"]
    assert sources(library) == before  # Search over what was ready keeps working.
    library.sync(wait=True)
    assert library.notices() == []  # Told once per failure, and not hammering Ollama.
    embedding.fail = None
    monkeypatch.setattr(rag, "monotonic", lambda: 10**9)
    library.sync(wait=True)
    assert library.status()["state"] == "ready" and "new" in sources(library)


def test_status_reports_every_state(folder, tmp_path):
    assert DocLibrary(None, BagOfWordsEmbedding()).status()["state"] == "off"
    empty, _ = make(folder.parent / "nothing", tmp_path)
    assert empty.status()["state"] == "empty" and empty.ready_count() == 0
    gate, started = threading.Event(), threading.Event()

    class Slow(BagOfWordsEmbedding):
        def embed(self, text):
            started.set()
            gate.wait(5)
            return super().embed(text)

    library = DocLibrary(str(folder), Slow(), "default")
    library.sync()
    assert started.wait(5) and library.status()["state"] == "indexing"
    gate.set()
    library.sync(wait=True)
    assert library.status()["state"] == "ready"


def test_put_adds_then_updates_and_a_listing_shows_it(folder, tmp_path):
    library, _ = make(folder, tmp_path)
    assert library.put("returns.md", "Returns are accepted within 30 days delivery") == "added"
    assert library.put("returns.md", "Returns are accepted within 14 days delivery") == "updated"
    library.sync(wait=True)
    assert any("14 days" in hit.text for hit in library.search("delivery"))
    assert not any("30 days" in hit.text for hit in library.search("delivery"))
    assert not [n for n in os.listdir(folder) if n.startswith(".upload")]


@pytest.mark.parametrize("name", ["../x.md", "a/b.md", ".hidden.md", "x" * 101 + ".md", "a b.md", "evil.py", "noext",
                                  "data.csv", "README.md", "readme.MD", "", None, 5])
def test_bad_names_and_types_are_refused(folder, tmp_path, name):
    library, _ = make(folder, tmp_path)
    before = sorted(os.listdir(folder))
    with pytest.raises(DocError):
        library.put(name, "text that is long enough")
    assert sorted(os.listdir(folder)) == before


def test_only_text_within_the_limits_is_accepted(folder, tmp_path):
    library, _ = make(folder, tmp_path)
    for text in ("a\x00b", 5, None):
        with pytest.raises(DocError):
            library.put("x.md", text)
    with pytest.raises(DocError, match="2 MB"):
        library.put("big.md", "x" * (2 * 2**20 + 1))
    small = tmp_path / "small"
    tight = DocLibrary(str(small), BagOfWordsEmbedding())
    for n in range(10):
        tight.put(f"p{n}.md", "x" * (2 * 2**20))
    with pytest.raises(DocError, match="20 MB"):
        tight.put("p10.md", "x")
    tight.put("p0.md", "y")  # Replacing frees its old size.


def test_a_symlink_is_never_written_through(folder, tmp_path):
    secret = tmp_path / "secret.md"
    secret.write_text("keep")
    os.symlink(secret, folder / "link.md")
    library, _ = make(folder, tmp_path)
    with pytest.raises(DocError):
        library.put("link.md", "overwritten text here")
    with pytest.raises(DocError):
        library.remove("link.md")
    assert secret.read_text() == "keep"


def test_a_switched_off_library_cannot_receive_files():
    with pytest.raises(DocError, match="switched off"):
        DocLibrary(None, BagOfWordsEmbedding()).put("a.md", "some text here")


def test_add_file_copies_from_anywhere_with_a_clean_name(folder, tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "My Documents").mkdir(parents=True)
    (home / "My Documents" / "Brand Voice v2 (final).md").write_text("Our tone is warm and clear voice", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    library, _ = make(folder, tmp_path)
    assert library.add_file("~/My Documents/Brand Voice v2 (final).md")[1] == "added"
    name = next(n for n in os.listdir(folder) if n.startswith("Brand-Voice"))
    assert (folder / name).read_text(encoding="utf-8") == "Our tone is warm and clear voice"
    assert (home / "My Documents" / "Brand Voice v2 (final).md").exists()  # Copied, not moved.


def test_add_file_errors_are_clear(folder, tmp_path):
    library, _ = make(folder, tmp_path)
    (tmp_path / "bad.md").write_bytes(b"\xff\xfe")
    (tmp_path / "pic.png").write_bytes(b"png")
    for path, message in ((tmp_path / "missing.md", "no such file"), (tmp_path / "bad.md", "not UTF-8"),
                          (tmp_path / "pic.png", "Only .md and .txt")):
        with pytest.raises(DocError, match=message):
            library.add_file(str(path))


def test_remove_deletes_the_file_and_the_index_entry(folder, tmp_path):
    library, _ = make(folder, tmp_path)
    library.remove("faq.md")
    assert "faq" not in sources(library) and not (folder / "faq.md").exists()
    with pytest.raises(DocError, match="No document named faq.md"):
        library.remove("faq.md")
    with pytest.raises(DocError):
        library.remove("../x.md")


def test_reindex_rebuilds_everything(folder, tmp_path):
    library, embedding = make(folder, tmp_path)
    library.reindex()
    assert library.status()["state"] == "ready" and library.ready_count() == 5


def test_search_marks_outdated_versions_and_reports_pending_documents(folder, tmp_path):
    library, _ = make(folder, tmp_path)
    result = search_docs_handler({"query": "cream"}, None, library=library)
    old = [line for line in result.output.splitlines() if line.startswith("[calm-barrier-cream-2025")]
    assert old and "OUTDATED: superseded by calm-barrier-cream 2026-09-01" in old[0]
    assert not any("OUTDATED" in l for l in result.output.splitlines() if l.startswith("[calm-barrier-cream,"))
    write(folder, "late.md", "More delivery news delivery")
    assert "1 more document is still being indexed" in search_docs_handler({"query": "cream"}, None, library=library).output


def test_the_tool_says_so_when_nothing_is_indexed(tmp_path):
    library = DocLibrary(str(tmp_path / "none"), BagOfWordsEmbedding())
    assert search_docs_handler({"query": "anything"}, None, library=library).output == "No relevant documents found"


def test_adding_while_searching_is_safe(folder, tmp_path):
    library, _ = make(folder, tmp_path)
    errors = []

    def search():
        try:
            for _ in range(30):
                library.search("delivery")
        except Exception as error:  # pragma: no cover
            errors.append(error)

    thread = threading.Thread(target=search)
    thread.start()
    for n in range(5):
        library.put(f"extra{n}.md", f"Extra paragraph number {n} about delivery")
    thread.join()
    library.sync(wait=True)
    assert errors == [] and library.ready_count() == 10


def test_add_command_takes_files_folders_and_quoted_paths(folder, tmp_path):
    library, _ = make(folder, tmp_path)
    source = tmp_path / "my docs"
    source.mkdir()
    (source / "one.md").write_text("First paragraph about price", encoding="utf-8")
    (source / "two.txt").write_text("Second paragraph about price", encoding="utf-8")
    (source / "skip.csv").write_text("a,b", encoding="utf-8")
    other = tmp_path / "three file.md"
    other.write_text("Third paragraph about price", encoding="utf-8")
    lines = add_command(library, f"'{source}' \"{other}\"")
    assert lines[:3] == ["Added one.md.", "Added two.txt.", "Added three-file.md."]
    assert lines[-1] == "Indexing in the background; /docs shows progress."
    library.sync(wait=True)
    assert library.ready_count() == 8
    assert add_command(library, str(other))[0] == "Updated three-file.md."
    assert add_command(library, "") == ["usage: /add <file or folder> [...]"]
    assert add_command(library, str(tmp_path / "nope.md")) == [f"error: {tmp_path / 'nope.md'}: no such file."]
    empty = tmp_path / "empty"
    empty.mkdir()
    assert add_command(library, str(empty)) == [f"{empty}: no .md or .txt files in that folder."]


def test_remove_and_docs_and_reindex_commands(folder, tmp_path):
    library, embedding = make(folder, tmp_path)
    assert remove_command(library, "") == ["usage: /remove <document name>"]
    assert remove_command(library, "faq.md") == ["Removed faq.md."]
    assert remove_command(library, "faq.md") == ["error: No document named faq.md."]
    lines = docs_command(library)
    assert lines[0] == "4 documents ready." and any(l.startswith("hydra-glow-serum.md   2026-09-01   ") for l in lines)
    hits = docs_command(library, "delivery cream")
    assert hits[0].startswith("[1] ") and len(hits) <= 3
    assert reindex_command(library)[0].startswith("Reindexed 4 documents")
    embedding.fail = EmbeddingError("Ollama embedding request failed")
    assert docs_command(library, "delivery") == ["error: Ollama embedding request failed"]


def test_docs_explains_each_state(folder, tmp_path):
    assert "/add a file" in docs_command(make(folder.parent / "nothing", tmp_path)[0])[0]
    assert docs_command(DocLibrary(None, BagOfWordsEmbedding()))[0] == "Document search is off."
    library, embedding = make(folder, tmp_path)
    embedding.fail = LLMConnectionError("cannot reach Ollama for embeddings")
    write(folder, "new.md", "Another paragraph about price")
    library.sync(wait=True)
    assert docs_command(library)[0] == "Document search is off: cannot reach Ollama for embeddings"
    assert reindex_command(library) == ["error: cannot reach Ollama for embeddings"]


def test_the_search_instructions_are_not_part_of_the_default_prompt():
    assert "search_docs" not in load_system_prompt() and "search_docs" in DOCS_PROMPT and "OUTDATED" in DOCS_PROMPT
