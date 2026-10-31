"""Web search in the page: the model's search, the sources event, /api/search and switching it off."""
from search_fakes import DUCK, Response
from sensai import search


def test_the_model_searches_and_the_sources_follow_the_reply(web, monkeypatch):
    monkeypatch.setattr(search.requests, "post", lambda *a, **k: Response(DUCK))
    page = web(['{"tool":"web_search","arguments":{"query":"skincare trends"}}'], ["Barrier care [1]."])
    _, events = page.stream({"text": "What is trending?"})
    sources = next(e for e in events if e["type"] == "web_sources")
    assert sources["items"] == [{"n": 1, "title": "Skin trends", "url": "https://example.com/trends", "date": ""}]
    assert [e["type"] for e in events].index("web_sources") < [e["type"] for e in events].index("done")


def test_slash_search_endpoint_and_clear_errors(web, monkeypatch):
    page = web()
    status, body = page.call("POST", "/api/search", {"query": "trends"})
    assert status == 503 and "check your connection" in body["error"]["message"]
    monkeypatch.setattr(search.requests, "post", lambda *a, **k: Response(DUCK))
    body = page.call("POST", "/api/search", {"query": "trends"})[1]
    assert body["provider"] == "duckduckgo" and body["items"][0]["snippet"] == "Barrier care is in."
    assert page.call("POST", "/api/search", {"query": " "})[0] == 400
    assert page.call("GET", "/api/config")[1]["capabilities"]["web_search"] is True


def test_search_can_be_switched_off(web, monkeypatch):
    monkeypatch.setenv("SENSAI_SEARCH_PROVIDER", "off")
    page = web()
    assert page.call("POST", "/api/search", {"query": "x"})[1]["error"]["code"] == "search_off"
    assert "web_search" not in page.call("GET", "/api/config")[1]["capabilities"]
