"""Web search (T3): a live query, the top five results, numbered for the model to cite.

Providers: Brave Search's API when SENSAI_SEARCH_API_KEY is set, otherwise DuckDuckGo's HTML
page (no key). SENSAI_SEARCH_PROVIDER=off switches search off.
"""
import html
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlparse

import requests

from sensai.core.errors import SensaiError
from sensai.core.ports import ToolDefinition, ToolResult

TOP = 5
TIMEOUT = 10
BRAVE = "https://api.search.brave.com/res/v1/web/search"
DUCKDUCKGO = "https://html.duckduckgo.com/html/"
WEB_SEARCH = ToolDefinition(
    "web_search",
    "Search the web for current information (trends, news, recent facts). Cite results as [1], [2].",
    {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
)


class SearchError(SensaiError):
    """Search is off, misconfigured or unreachable; the message says which."""


@dataclass(frozen=True)
class Result:
    title: str
    url: str
    snippet: str
    date: str = ""


class _DuckParser(HTMLParser):
    """Titles, links and snippets from DuckDuckGo's HTML results page."""

    def __init__(self):
        super().__init__()
        self.results: list[dict] = []
        self._field = None

    def handle_starttag(self, tag, attrs):
        classes = dict(attrs).get("class") or ""
        if tag == "a" and "result__a" in classes:
            href = dict(attrs).get("href") or ""
            target = parse_qs(urlparse(href).query).get("uddg", [href])[0]
            self.results.append({"title": "", "url": target, "snippet": ""})
            self._field = "title"
        elif "result__snippet" in classes and self.results:
            self._field = "snippet"

    def handle_endtag(self, tag):
        if tag in ("a", "td", "div"):
            self._field = None

    def handle_data(self, data):
        if self._field and self.results:
            self.results[-1][self._field] += data


def _brave(query: str, key: str) -> list[Result]:
    response = requests.get(BRAVE, params={"q": query, "count": TOP}, timeout=TIMEOUT,
                            headers={"Accept": "application/json", "X-Subscription-Token": key})
    if response.status_code in (401, 403):
        raise SearchError("the search API key was refused (check SENSAI_SEARCH_API_KEY)")
    response.raise_for_status()
    items = response.json().get("web", {}).get("results", [])
    return [Result(i.get("title", ""), i.get("url", ""), html.unescape(i.get("description", "")), i.get("page_age", "")[:10])
            for i in items]


def _duckduckgo(query: str) -> list[Result]:
    response = requests.post(DUCKDUCKGO, data={"q": query}, timeout=TIMEOUT, headers={"User-Agent": "Mozilla/5.0 Sensai"})
    response.raise_for_status()
    parser = _DuckParser()
    parser.feed(response.text)
    if not parser.results and "serp__results" not in response.text:
        # Not a real empty result: DuckDuckGo turned the request away (it limits automated requests).
        raise SearchError("DuckDuckGo did not answer this time; try again in a moment, or set SENSAI_SEARCH_API_KEY")
    return [Result(" ".join(r["title"].split()), r["url"], " ".join(r["snippet"].split())) for r in parser.results]


def search(query: str, provider: str, key: str | None = None) -> list[Result]:
    """The top results for `query` (possibly none); SearchError when search cannot run."""
    if provider == "off":
        raise SearchError("web search is switched off (SENSAI_SEARCH_PROVIDER=off)")
    if provider == "brave" and not key:
        raise SearchError("web search is not configured: set SENSAI_SEARCH_API_KEY for Brave Search")
    try:
        found = _brave(query, key) if provider == "brave" else _duckduckgo(query)
    except requests.RequestException as exc:
        raise SearchError(f"the web search failed ({type(exc).__name__}); check your connection") from None
    except ValueError:
        raise SearchError("the search service answered with something unreadable") from None
    return [r for r in found if r.url.startswith(("http://", "https://")) and r.title][:TOP]


def numbered(results: list[Result]) -> str:
    return "\n".join(f"[{n}] {r.title}{f' ({r.date})' if r.date else ''}\n{r.url}\n{r.snippet}" for n, r in enumerate(results, 1))


class WebSearch:
    """The web_search tool; keeps this turn's results so the caller can list the sources."""

    def __init__(self, provider: str, key: str | None = None, on_search=None):
        self.provider, self.key = provider, key
        self.on_search = on_search  # called with the query before searching ("Searching the web for: …")
        self.results: list[Result] = []

    def __call__(self, arguments, cancellation=None) -> ToolResult:
        query = arguments.get("query")
        if not isinstance(query, str) or not query.strip():
            return ToolResult("", "give a query")
        if self.on_search:
            self.on_search(query.strip())
        try:
            found = search(query.strip(), self.provider, self.key)
        except SearchError as exc:
            return ToolResult("", f"Web search unavailable: {exc}. Answer without it and say so.")
        if not found:
            return ToolResult(f"No web results for {query.strip()!r}. Say that nothing was found; do not invent sources.")
        start = len(self.results)  # Numbers go on across searches in one turn, so [n] stays unique.
        self.results.extend(found)
        return ToolResult("\n".join(f"[{start + n}] {r.title}{f' ({r.date})' if r.date else ''}\n{r.url}\n{r.snippet}"
                                    for n, r in enumerate(found, 1)))


def provider_for(setting: str | None, key: str | None) -> str:
    return (setting or ("brave" if key else "duckduckgo")).lower()
