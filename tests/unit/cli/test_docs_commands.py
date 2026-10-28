"""/docs, /reindex and document search wiring in the REPL and at startup."""
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from fakes import FakeClient, BagOfWordsEmbedding, scripted_terminal
from sensai.chat.session import ChatSession
from sensai.cli import main as cli
from sensai.core.errors import ModelNotFoundError
from sensai.memory.vector_index import LocalVectorIndex
from sensai.rag import DOCS_PROMPT, DocSearch, build_index, load_documents
from sensai.tools import ToolRegistry

pytestmark = pytest.mark.usefixtures("isolated_settings")
FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "docs"


@pytest.fixture
def search(tmp_path):
    folder = tmp_path / "docs"
    shutil.copytree(FIXTURES, folder)
    embedding = BagOfWordsEmbedding()
    index = LocalVectorIndex(embedding)
    docs = load_documents(str(folder))
    build_index(docs, embedding, index, "default")
    return DocSearch(index, docs, str(folder), "default", "nomic-embed-text")


def run(inputs, docs, client=None):
    client = client or FakeClient()
    session = ChatSession(client, "model", "Shared rules")
    queue = iter(inputs)
    out = []
    cli.repl(session, read=lambda _: next(queue), write=lambda text="", **kw: out.append(text), docs=docs)
    return out, client


def test_docs_and_reindex_do_not_call_the_model(search):
    out, client = run(["/docs", "/docs delivery", "/reindex", "exit"], search)
    assert client.requests == []
    assert any(line.startswith("faq   2026-09-01") for line in out)
    assert any(line.startswith("[1] faq") for line in out)
    assert out[-1].startswith("Reindexed 5 documents")


def test_without_a_docs_folder_the_commands_say_search_is_off():
    out, client = run(["/docs", "/docs delivery", "/reindex", "exit"], None)
    assert out == ["Document search is off (no --docs folder)."] * 3 and client.requests == []


def test_a_failing_embedding_model_does_not_end_the_chat(search):
    search.index.embedding.fail = ModelNotFoundError("Ollama embedding model not found")
    out, client = run(["/docs delivery", "/reindex", "Hello", "exit"], search, FakeClient(["Hi there"]))
    expected = "error: Ollama embedding model not found (try: ollama pull nomic-embed-text)"
    assert out.count(expected) == 2
    assert "Hi there" in out  # The next question is still answered.


def test_the_docs_argument_may_contain_extra_spaces(search):
    out, _ = run(["/docs    cruelty   ", "exit"], search)
    assert out[0].startswith("[1] faq")


def args(tmp_path, docs):
    return SimpleNamespace(docs=docs, creator="default")


def settings():
    return SimpleNamespace(embed_model="nomic-embed-text")


def test_setup_is_a_no_op_without_a_folder(tmp_path):
    registry = ToolRegistry()
    assert cli._setup_rag(args(tmp_path, None), settings(), registry) is None
    assert [d.name for d in registry.definitions()] == []


def test_setup_indexes_registers_the_tool_and_reports(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "OllamaEmbeddingAdapter", lambda model: BagOfWordsEmbedding())
    registry = ToolRegistry()
    found = cli._setup_rag(args(tmp_path, str(FIXTURES)), settings(), registry)
    assert isinstance(found, DocSearch) and len(found.docs) == 5
    assert [d.name for d in registry.definitions()] == ["search_docs"]
    assert "Indexed 5 documents" in capsys.readouterr().out


def test_setup_warns_about_files_without_a_header_and_empty_folders(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "OllamaEmbeddingAdapter", lambda model: BagOfWordsEmbedding())
    (tmp_path / "notes.md").write_text("no header here at all")
    registry = ToolRegistry()
    assert cli._setup_rag(args(tmp_path, str(tmp_path)), settings(), registry) is None
    out = capsys.readouterr().out
    assert "warning: skipped notes.md" in out and "no documents found" in out
    assert registry.definitions() == ()


def test_setup_turns_a_missing_embedding_model_into_a_warning(tmp_path, monkeypatch, capsys):
    def missing(model):
        raise ModelNotFoundError("Ollama embedding model not found")

    monkeypatch.setattr(cli, "OllamaEmbeddingAdapter", missing)
    registry = ToolRegistry()
    assert cli._setup_rag(args(tmp_path, str(FIXTURES)), settings(), registry) is None
    out = capsys.readouterr().out
    assert "warning: document search is off: Ollama embedding model not found" in out
    assert "run: ollama pull nomic-embed-text" in out and registry.definitions() == ()


def chat(monkeypatch, tmp_path, *argv):
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Shared rules")
    client = FakeClient(["Answer"])
    monkeypatch.setattr(cli, "create_client", lambda settings: client)
    monkeypatch.setattr(cli, "TerminalInput", scripted_terminal(["Question", "exit"]))
    monkeypatch.setattr(cli, "OllamaEmbeddingAdapter", lambda model: BagOfWordsEmbedding())
    cli.main(["model", "--prompt", str(prompt), "--db", str(tmp_path / "s.db"), *argv])
    return client


def test_the_search_instructions_reach_the_model_only_when_search_is_on(monkeypatch, tmp_path):
    (tmp_path / "on").mkdir()
    with_docs = chat(monkeypatch, tmp_path / "on", "--docs", str(FIXTURES))
    assert DOCS_PROMPT in with_docs.calls[0][0] and "search_docs" in with_docs.calls[0][0]
    without = chat(monkeypatch, tmp_path)
    assert "search_docs" not in without.calls[0][0] and DOCS_PROMPT not in without.calls[0][0]
