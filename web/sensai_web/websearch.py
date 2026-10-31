"""Web search (T3) in the page: the model's tool, the sources under the reply, and /search."""
from sensai.search import SearchError, WebSearch, provider_for, search
from sensai_web.errors import ApiError


def make(settings) -> WebSearch | None:
    tool = WebSearch(provider_for(settings.search_provider, settings.search_api_key), settings.search_api_key)
    return None if tool.provider == "off" else tool


def items(results) -> list[dict]:
    return [{"n": n, "title": r.title, "url": r.url, "date": r.date} for n, r in enumerate(results, 1)]


def sources(app, emit) -> None:
    """After a completed reply: the web results it could cite, numbered as the model saw them."""
    if app.web is not None and app.web.results:
        emit({"type": "web_sources", "items": items(app.web.results)})


def run(app, query: object) -> dict:
    if app.web is None:
        raise ApiError(409, "search_off", "Web search is switched off (SENSAI_SEARCH_PROVIDER=off).")
    if not isinstance(query, str) or not query.strip():
        raise ApiError(400, "bad_request", "Write what to search for.")
    try:
        found = search(query.strip(), app.web.provider, app.web.key)
    except SearchError as exc:
        raise ApiError(503, "search_unavailable", f"Web search unavailable: {exc}") from None
    return {"query": query.strip(), "provider": app.web.provider,
            "items": [{**i, "snippet": r.snippet} for i, r in zip(items(found), found)]}
