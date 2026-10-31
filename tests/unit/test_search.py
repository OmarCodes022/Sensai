"""Web search: the two providers, clear errors, numbered results and the tool's running source list."""
import pytest

from sensai import search
from sensai.search import SearchError, WebSearch, provider_for
from search_fakes import DUCK, Response

def test_duckduckgo_results_are_parsed_and_unsafe_links_dropped(monkeypatch):
    monkeypatch.setattr(search.requests, "post", lambda *a, **k: Response(DUCK))
    (result,) = search.search("skin trends", "duckduckgo")
    assert (result.title, result.url, result.snippet) == ("Skin trends", "https://example.com/trends", "Barrier care is in.")


def test_brave_needs_a_key_and_reads_its_json(monkeypatch):
    with pytest.raises(SearchError, match="SENSAI_SEARCH_API_KEY"):
        search.search("q", "brave")
    payload = {"web": {"results": [{"title": "T", "url": "https://a.example", "description": "S &amp; more", "page_age": "2026-10-12T10:00"}]}}
    monkeypatch.setattr(search.requests, "get", lambda *a, **k: Response(payload=payload))
    (result,) = search.search("q", "brave", "key")
    assert (result.snippet, result.date) == ("S & more", "2026-10-12")
    monkeypatch.setattr(search.requests, "get", lambda *a, **k: Response(status=401))
    with pytest.raises(SearchError, match="refused"):
        search.search("q", "brave", "bad")


def test_network_errors_and_off_are_clear_messages():
    with pytest.raises(SearchError, match="check your connection"):
        search.search("q", "duckduckgo")
    with pytest.raises(SearchError, match="switched off"):
        search.search("q", "off")
    assert provider_for(None, None) == "duckduckgo" and provider_for(None, "k") == "brave" and provider_for("OFF", "k") == "off"


def test_the_tool_numbers_results_across_searches_and_never_breaks(monkeypatch):
    monkeypatch.setattr(search.requests, "post", lambda *a, **k: Response(DUCK))
    seen = []
    tool = WebSearch("duckduckgo", on_search=seen.append)
    assert tool({"query": "skin"}).output.startswith("[1] Skin trends\nhttps://example.com/trends")
    assert tool({"query": "more"}).output.startswith("[2] Skin trends") and seen == ["skin", "more"]
    monkeypatch.setattr(search.requests, "post", lambda *a, **k: Response('<div class="serp__results">No results.</div>'))
    assert "No web results" in WebSearch("duckduckgo")({"query": "zzz"}).output
    monkeypatch.setattr(search.requests, "post", lambda *a, **k: Response("<p>challenge</p>"))
    assert "did not answer this time" in WebSearch("duckduckgo")({"query": "zzz"}).error
    assert "Web search unavailable" in WebSearch("brave")({"query": "q"}).error
