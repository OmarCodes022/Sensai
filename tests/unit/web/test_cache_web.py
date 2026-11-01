"""A6 in the page: a new session's first question may be answered from the cache, with a `cached` event."""
from sensai.memory.semantic_cache import SemanticCache


def embed(text):
    low = text.lower()
    return tuple(float(word in low) + 0.01 for word in ("serum", "cream", "hydrate", "price"))


def test_a_new_sessions_similar_first_question_is_served_from_the_cache(web, tmp_path):
    page = web(["It hydrates for up to 8 hours."], ["A follow-up answer."])
    page.app.cache = SemanticCache(str(tmp_path / "c.db"), embed)
    page.stream({"text": "Does the serum hydrate?"})
    page.stream({"text": "Does the serum hydrate?"})  # A follow-up: the model answers.
    assert len(page.client.requests) == 2
    page.call("POST", "/api/sessions", {})
    _, events = page.stream({"text": "How does the serum hydrate skin?"})
    cached = next(e for e in events if e["type"] == "cached")
    assert cached["question"] == "Does the serum hydrate?" and cached["similarity"] > 0.99
    assert "".join(e["delta"] for e in events if e["type"] == "text") == "It hydrates for up to 8 hours."
    assert len(page.client.requests) == 2 and events[-1]["status"] == "completed"
    items = page.call("GET", "/api/session")[1]["items"]
    assert [i["text"] for i in items] == ["How does the serum hydrate skin?", "It hydrates for up to 8 hours."]


def test_the_cache_capability_follows_the_setting(web, monkeypatch):
    assert "cache" not in web(["hi"]).call("GET", "/api/config")[1]["capabilities"]
