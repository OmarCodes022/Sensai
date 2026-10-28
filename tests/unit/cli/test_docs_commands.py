"""Document search in the terminal chat: slash commands, the prompt following the documents, startup wiring."""
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from fakes import BagOfWordsEmbedding, FakeClient, scripted_terminal
from sensai.chat.personas import PersonaRegistry
from sensai.chat.session import ChatSession
from sensai.cli import main as cli
from sensai.core.errors import ModelNotFoundError
from sensai.rag import DOCS_PROMPT, DocLibrary
from sensai.tools import ToolRegistry

pytestmark = pytest.mark.usefixtures("isolated_settings")
FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "docs"


@pytest.fixture
def library(tmp_path):
    folder = tmp_path / "docs"
    shutil.copytree(FIXTURES, folder)
    return DocLibrary(str(folder), BagOfWordsEmbedding(), "default", cache_path=str(tmp_path / "s.db"))


def run(inputs, docs, client=None, **kwargs):
    """Drive the real REPL; each read waits for background indexing, like a person typing slowly."""
    client = client or FakeClient()
    session = ChatSession(client, "model", "Shared rules")
    queue, out = iter(inputs), []

    def read(_):
        if docs is not None:
            docs.sync(wait=True)
        return next(queue)

    cli.repl(session, read=read, write=lambda text="", **kw: out.append(text), docs=docs, **kwargs)
    return out, client, session


def system(session):
    return session.messages[0].content


def test_a_ready_library_gives_the_model_the_search_instructions_without_any_command(library):
    library.sync(wait=True)
    out, client, session = run(["Hello", "exit"], library, FakeClient(["Hi"]))
    assert DOCS_PROMPT in client.calls[0][0] and "search_docs" in client.calls[0][0]
    assert "Document search: 5 documents indexed." in out  # Told once, at the prompt.


def test_with_no_documents_the_prompt_has_no_search_instructions(tmp_path):
    empty = DocLibrary(str(tmp_path / "none"), BagOfWordsEmbedding())
    out, client, _ = run(["Hello", "exit"], empty, FakeClient(["Hi"]))
    assert DOCS_PROMPT not in client.calls[0][0] and "Hi" in out and not any("Document search" in l for l in out)


def test_without_a_library_the_commands_say_search_is_off():
    out, client, _ = run(["/docs", "/add x.md", "/remove x.md", "/reindex", "exit"], None)
    assert out == ["Document search is off (SENSAI_DOCS is empty)."] * 4 and client.requests == []


def test_the_commands_never_call_the_model(library):
    out, client, _ = run(["/docs", "/docs cream", "/reindex", "/remove faq.md", "exit"], library)
    assert client.requests == []
    assert any(line.endswith("documents ready.") for line in out) and "Removed faq.md." in out


def test_add_during_a_chat_turns_the_search_instructions_on_for_the_next_question(tmp_path):
    empty = DocLibrary(str(tmp_path / "docs"), BagOfWordsEmbedding(), "default")
    source = tmp_path / "voice.md"
    source.write_text("Our voice is warm and clear voice", encoding="utf-8")
    out, client, session = run(["First", f"/add {source}", "Second", "exit"], empty, FakeClient(["A"], ["B"]))
    assert DOCS_PROMPT not in client.calls[0][0] and DOCS_PROMPT in client.calls[1][0]
    assert "Added voice.md." in out and system(session).count(DOCS_PROMPT) == 1


def test_removing_the_last_document_turns_them_off_again(tmp_path):
    folder = tmp_path / "docs"
    folder.mkdir()
    (folder / "only.md").write_text("The only paragraph about price", encoding="utf-8")
    only = DocLibrary(str(folder), BagOfWordsEmbedding(), "default")
    out, client, _ = run(["First", "/remove only.md", "Second", "exit"], only, FakeClient(["A"], ["B"]))
    assert DOCS_PROMPT in client.calls[0][0] and DOCS_PROMPT not in client.calls[1][0]


def test_a_dropped_in_file_is_noticed_at_the_next_prompt(library):
    library.sync(wait=True)
    folder = Path(library.folder)

    def drop():
        (folder / "shipping.md").write_text("Shipping to Canada takes nine days delivery", encoding="utf-8")

    run(["First", "exit"], library, FakeClient(["A"]))
    drop()
    out2, _, _ = run(["/docs", "exit"], library)  # The prompt after a command is where news is shown.
    assert "Document search: 1 document indexed." in out2


def test_the_persona_switch_keeps_the_search_instructions(library):
    library.sync(wait=True)
    out, client, session = run(["Hello", "/persona analyse", "Again", "exit"], library, FakeClient(["A"], ["B"]),
                               persona_registry=PersonaRegistry.from_file())
    assert DOCS_PROMPT in client.calls[1][0] and "Persona: Analyse" in client.calls[1][0]
    assert system(session).count("Available tools") == 1


def test_a_failing_embedding_model_does_not_end_the_chat(library):
    library.sync(wait=True)
    library.embedding.fail = ModelNotFoundError("Ollama embedding model not found")
    out, client, _ = run(["/docs delivery", "Hello", "exit"], library, FakeClient(["Hi there"]))
    assert "error: Ollama embedding model not found (run: ollama pull embedding)" in out
    assert "Hi there" in out


def args(**kwargs):
    return SimpleNamespace(docs="data/docs", creator="default", host="http://localhost:11434", db="s.db", **kwargs)


def settings():
    return SimpleNamespace(embed_model="nomic-embed-text")


def test_setup_is_a_no_op_when_search_is_switched_off(real_setup_docs):
    registry = ToolRegistry()
    assert cli._setup_docs(SimpleNamespace(docs="", creator="default"), settings(), registry) is None
    assert registry.definitions() == ()


def test_setup_registers_the_tool_and_starts_indexing(real_setup_docs, tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "OllamaEmbeddingAdapter", lambda model, host=None: BagOfWordsEmbedding())
    folder = tmp_path / "docs"
    shutil.copytree(FIXTURES, folder)
    registry = ToolRegistry()
    found = cli._setup_docs(SimpleNamespace(docs=str(folder), creator="default", host="h", db=str(tmp_path / "s.db")),
                            settings(), registry)
    assert isinstance(found, DocLibrary) and [d.name for d in registry.definitions()] == ["search_docs"]
    found.sync(wait=True)
    assert found.status()["state"] == "ready" and found.ready_count() == 5


def chat(monkeypatch, tmp_path, *argv):
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Shared rules")
    client = FakeClient(["Answer"])
    monkeypatch.setattr(cli, "create_client", lambda settings: client)
    monkeypatch.setattr(cli, "TerminalInput", scripted_terminal(["Question", "exit"]))
    monkeypatch.setattr(cli, "OllamaEmbeddingAdapter", lambda model, host=None: BagOfWordsEmbedding())
    cli.main(["model", "--prompt", str(prompt), "--db", str(tmp_path / "s.db"), *argv])
    return client


def test_the_default_folder_is_data_docs_and_search_follows_what_is_in_it(real_setup_docs, monkeypatch, tmp_path):
    work = tmp_path / "work"
    (work / "data" / "docs").mkdir(parents=True)
    shutil.copy(FIXTURES / "faq.md", work / "data" / "docs" / "faq.md")
    monkeypatch.chdir(work)
    with_docs = chat(monkeypatch, tmp_path)  # No --docs flag: ./data/docs is used.
    assert "search_docs" in with_docs.calls[0][0]
    (work / "data" / "docs" / "faq.md").unlink()
    without = chat(monkeypatch, tmp_path / "again") if (tmp_path / "again").mkdir() is None else None
    assert DOCS_PROMPT not in without.calls[0][0]


def test_docs_can_point_elsewhere_or_be_switched_off(real_setup_docs, monkeypatch, tmp_path):
    other = tmp_path / "elsewhere"
    shutil.copytree(FIXTURES, other)
    assert "search_docs" in chat(monkeypatch, tmp_path, "--docs", str(other)).calls[0][0]
    (tmp_path / "off").mkdir()
    off = chat(monkeypatch, tmp_path / "off", "--docs", "")
    assert "search_docs" not in off.calls[0][0]
