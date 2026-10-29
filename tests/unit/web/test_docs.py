"""Brand documents in the web: the endpoints, the model's search tool, sources, and the prompt following the documents."""
import shutil
from pathlib import Path
from urllib.parse import quote

import pytest

from sensai.core.errors import LLMConnectionError, ModelNotFoundError
from sensai.rag import DOCS_PROMPT

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "docs"
SEARCH = '{"tool": "search_docs", "arguments": {"query": "delivery"}}'


@pytest.fixture
def docs_dir(tmp_path):
    folder = tmp_path / "docs"
    shutil.copytree(FIXTURES, folder)
    return str(folder)


def ready(page):
    page.app.docs.sync(wait=True)
    return page


def kinds(events):
    return [e["type"] for e in events]


def test_documents_are_off_when_the_folder_is_switched_off(web):
    page = web()
    assert "documents" not in page.call("GET", "/api/config")[1]["capabilities"]
    assert page.call("GET", "/api/docs")[1]["state"] == "off"
    assert [t["name"] for t in page.call("GET", "/api/tools")[1]["items"]] == ["calculate", "run_python"]
    status, body = page.call("PUT", "/api/docs/a.md", {"text": "some text here"})
    assert status == 400 and "switched off" in body["error"]["message"]
    assert page.call("POST", "/api/docs/reindex")[0] == 400


def test_the_capability_and_the_tool_appear_with_documents(web, docs_dir):
    page = web(docs_dir=docs_dir)
    assert page.call("GET", "/api/config")[1]["capabilities"]["documents"] is True
    assert [t["name"] for t in page.call("GET", "/api/tools")[1]["items"]][-1] == "search_docs"


def test_the_folder_is_listed_and_indexes_by_itself(web, docs_dir):
    page = ready(web(docs_dir=docs_dir))
    body = page.call("GET", "/api/docs")[1]
    assert (body["state"], body["documents"], body["pending"], body["embed_model"]) == ("ready", 5, 0, "nomic-embed-text")
    assert body["limits"] == {"file_mb": 2, "total_mb": 20, "types": [".md", ".txt"]}
    names = [d["name"] for d in body["items"]]
    assert names[:2] == ["brand-voice.md", "calm-barrier-cream-2025.md"] and "README.md" not in names
    faq = next(d for d in body["items"] if d["name"] == "faq.md")
    assert faq["state"] == "ready" and faq["version"] == "2026-09-01" and faq["chunks"] > 0


def test_a_file_dropped_into_the_folder_shows_up_without_any_request(web, docs_dir):
    page = ready(web(docs_dir=docs_dir))
    (Path(docs_dir) / "shipping.md").write_text("Shipping to Canada takes nine days delivery", encoding="utf-8")
    first = page.call("GET", "/api/docs")[1]  # The page polls this.
    assert first["pending"] in (0, 1)
    page.app.docs.sync(wait=True)
    assert "shipping.md" in [d["name"] for d in page.call("GET", "/api/docs")[1]["items"]]


def test_a_document_is_added_replaced_and_removed(web, docs_dir):
    page = ready(web(docs_dir=docs_dir))
    status, body = page.call("PUT", "/api/docs/returns.md", {"text": "Returns are accepted within 30 days delivery"})
    assert status == 200 and "returns.md" in [d["name"] for d in body["items"]]
    page.call("PUT", "/api/docs/returns.md", {"text": "Returns are accepted within 14 days delivery"})
    assert "14 days" in (Path(docs_dir) / "returns.md").read_text()
    page.app.docs.sync(wait=True)
    status, body = page.call("DELETE", "/api/docs/returns.md")
    assert status == 200 and "returns.md" not in [d["name"] for d in body["items"]]
    assert not (Path(docs_dir) / "returns.md").exists()
    assert page.call("DELETE", "/api/docs/returns.md")[0] == 404


@pytest.mark.parametrize("name", ["../x.md", "a/b.md", ".hidden.md", "evil.py", "noext", "data.csv", "README.md", "a b.md"])
def test_bad_names_and_types_are_refused(web, docs_dir, name):
    page = web(docs_dir=docs_dir)
    before = sorted(p.name for p in Path(docs_dir).iterdir())
    status, body = page.call("PUT", f"/api/docs/{quote(name, safe='')}", {"text": "text that is long enough"})
    assert status == 400 and body["error"]["code"] == "bad_document"
    assert sorted(p.name for p in Path(docs_dir).iterdir()) == before


def test_limits_and_bad_bodies(web, docs_dir):
    page = web(docs_dir=docs_dir)
    status, body = page.call("PUT", "/api/docs/big.md", {"text": "x" * (2 * 2**20 + 1)})
    assert status == 413 and "2 MB" in body["error"]["message"]
    assert page.call("PUT", "/api/docs/a.md", {"text": "a\x00b"})[0] == 400
    assert page.call("PUT", "/api/docs/a.md", {})[0] == 400
    assert page.call("PUT", "/api/docs/a.md", {"text": 5})[0] == 400


def test_document_changes_need_the_pages_own_origin(web, docs_dir):
    page = web(docs_dir=docs_dir)
    evil = {"Origin": "http://evil.example"}
    assert page.call("PUT", "/api/docs/a.md", {"text": "some text here"}, headers=evil)[0] == 403
    assert page.call("DELETE", "/api/docs/faq.md", headers=evil)[0] == 403
    assert page.call("POST", "/api/docs/reindex", headers=evil)[0] == 403
    assert (Path(docs_dir) / "faq.md").exists() and not (Path(docs_dir) / "a.md").exists()


def test_reindex_rebuilds_the_index(web, docs_dir):
    page = ready(web(docs_dir=docs_dir))
    body = page.call("POST", "/api/docs/reindex")[1]
    assert body["state"] == "ready" and body["documents"] == 5


def test_search_previews_what_the_model_would_find(web, docs_dir):
    page = ready(web(docs_dir=docs_dir))
    status, body = page.call("GET", "/api/docs/search?q=delivery")
    assert status == 200 and body["items"][0]["source"] == "faq" and "2 or 3 business days" in body["items"][0]["text"]
    assert page.call("GET", "/api/docs/search?q=")[0] == 400
    assert page.call("GET", "/api/docs/search")[0] == 400


@pytest.mark.parametrize("error, code, hint", [
    (ModelNotFoundError("Ollama embedding model not found"), "model_not_found", "ollama pull nomic-embed-text"),
    (LLMConnectionError("cannot reach Ollama for embeddings"), "connection", "ollama serve"),
])
def test_a_missing_embedding_model_is_reported_not_fatal(web, docs_dir, error, code, hint):
    page = ready(web(docs_dir=docs_dir))
    page.app.docs.embedding.fail = error
    status, body = page.call("GET", "/api/docs/search?q=delivery")
    assert status == 503 and (body["error"]["code"], body["error"]["hint"]) == (code, hint)
    assert page.call("GET", "/api/docs")[0] == 200


def test_a_failing_embedding_model_shows_as_unavailable_with_the_fix(web, docs_dir):
    page = ready(web(docs_dir=docs_dir))
    page.app.docs.embedding.fail = ModelNotFoundError("Ollama embedding model not found")
    (Path(docs_dir) / "new.md").write_text("A new paragraph about price", encoding="utf-8")
    page.app.docs.sync(wait=True)
    body = page.call("GET", "/api/docs")[1]
    assert body["state"] == "unavailable" and "ollama pull nomic-embed-text" in body["error"]


def test_the_model_searches_the_documents_and_the_page_gets_its_sources(web, docs_dir):
    page = ready(web([f"Let me check.\n{SEARCH}"], ["Delivery takes 2 or 3 business days (faq)."], docs_dir=docs_dir))
    _, events = page.stream({"text": "How long is delivery?"})
    assert kinds(events) == ["turn_start", "warning", "text", "tool_call", "tool_result", "sources", "text", "usage", "saved", "title", "done"]
    assert events[1]["code"] == "documents" and "5 documents indexed" in events[1]["message"]
    result = next(e for e in events if e["type"] == "tool_result")
    assert result["ok"] is True and "[faq, 2026-09-01]" in result["output"]
    sources = next(e for e in events if e["type"] == "sources")["items"]
    assert sources[0]["source"] == "faq" and sources[0]["n"] == 1 and {"version", "score", "outdated"} <= set(sources[0])


def test_the_search_instructions_follow_the_documents(web, docs_dir):
    page = ready(web(["A"], ["B"], ["C"], docs_dir=docs_dir))
    page.stream({"text": "one"})
    assert DOCS_PROMPT in page.client.calls[0][0] and "search_docs" in page.client.calls[0][0]
    for name in [d["name"] for d in page.call("GET", "/api/docs")[1]["items"]]:
        page.call("DELETE", f"/api/docs/{name}")
    page.stream({"text": "two"})
    assert DOCS_PROMPT not in page.client.calls[1][0]
    page.call("PUT", "/api/docs/new.md", {"text": "A new paragraph about price"})
    page.app.docs.sync(wait=True)
    page.stream({"text": "three"})
    assert DOCS_PROMPT in page.client.calls[2][0]
    assert sum(m.content.count(DOCS_PROMPT) for m in page.app.active.session.messages) == 1


def test_without_documents_the_prompt_never_mentions_search(web, tmp_path):
    page = web(["A"], docs_dir=str(tmp_path / "empty"))
    page.stream({"text": "hello"})
    assert DOCS_PROMPT not in page.client.calls[0][0]


def test_the_persona_switch_keeps_the_search_instructions(web, docs_dir):
    page = ready(web(["A"], docs_dir=docs_dir))
    page.call("POST", "/api/persona", {"id": "analyse"})
    page.stream({"text": "hello"})
    first = page.client.calls[0][0]
    assert DOCS_PROMPT in first and "Persona: Analyse" in first


def test_a_failing_search_inside_a_turn_is_a_tool_error_not_a_crash(web, docs_dir):
    page = ready(web([SEARCH], ["I could not search."], docs_dir=docs_dir))
    page.app.docs.embedding.fail = LLMConnectionError("cannot reach Ollama for embeddings")
    _, events = page.stream({"text": "delivery?"})
    result = next(e for e in events if e["type"] == "tool_result")
    assert result["ok"] is False and "cannot reach Ollama" in result["error"]
    assert "sources" not in kinds(events) and events[-1]["status"] == "completed"


def test_a_document_can_be_read_for_the_viewer(web, docs_dir):
    page = ready(web(docs_dir=docs_dir))
    status, body = page.call("GET", "/api/docs/faq.md")
    assert status == 200 and body["name"] == "faq.md" and "Delivery takes 2 or 3 business days" in body["text"]
    assert (body["source"], body["version"]) == ("faq", "2026-09-01") and body["chunks"] > 0 and body["bytes"] == len(body["text"].encode())
    assert page.call("GET", "/api/docs/search?q=delivery")[0] == 200  # Not shadowed by the name route.
    assert page.call("GET", "/api/docs/nope.md")[0] == 404
    assert page.call("GET", "/api/docs/evil.py")[0] == 400
    assert page.call("GET", f"/api/docs/{quote('../x.md', safe='')}")[0] == 400


def test_a_document_not_yet_indexed_can_still_be_read(web, docs_dir):
    page = ready(web(docs_dir=docs_dir))
    (Path(docs_dir) / "fresh.md").write_text("A fresh note about price", encoding="utf-8")
    status, body = page.call("GET", "/api/docs/fresh.md")
    assert status == 200 and body["text"] == "A fresh note about price" and "chunks" not in body
