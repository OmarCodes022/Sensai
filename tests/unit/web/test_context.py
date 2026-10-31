"""M2 in the page: the count after each turn, summarizing at 80%, /api/context and /compact."""
from fakes import FakeClient
from sensai.chat import compression
from sensai.core.errors import LLMError
from sensai.llm.ollama_api import OllamaUsage


class Reporting(FakeClient):
    """Reports one scripted token count per request to the app's usage collector."""

    def __init__(self, counts, *replies):
        super().__init__(*replies)
        self.counts, self.sink = list(counts), None

    def stream(self, model, messages, cancellation=None):
        yield from super().stream(model, messages, cancellation)
        count = self.counts.pop(0)
        self.sink(OllamaUsage(prompt_tokens=count - 5, output_tokens=5, latency_ms=1.0))


def start(web, counts, *replies, **overrides):
    client = Reporting(counts, *replies)
    page = web(client=client, **overrides)
    client.sink = page.app.usage.add
    return page


def kinds(events):
    return [event["type"] for event in events]


def test_context_reports_the_window_and_the_last_count(web):
    page = start(web, [300], ["A1"])
    assert page.call("GET", "/api/context")[1]["last_tokens"] is None
    page.stream({"text": "Q1"})
    status, body = page.call("GET", "/api/context")
    assert status == 200
    assert body == {"budget": 4096, "source": "default", "last_tokens": 300, "summaries": 0, "saved": 0,
                    "threshold": compression.THRESHOLD}
    assert page.call("GET", "/api/config")[1]["capabilities"]["context_budget"] is True


def test_a_turn_at_eighty_percent_summarizes_older_messages(web):
    page = start(web, [30, 50, 85, 20, 40], ["A1"], ["A2"], ["A3"], ["Launch 14 November."], ["A4"],
                 context_length=100)
    for question in ("Q1", "Q2"):
        page.stream({"text": question})
    _, events = page.stream({"text": "Q3"})
    assert kinds(events)[-3:] == ["compacting", "compacted", "done"]
    assert events[-3]["messages"] == 2 and events[-3]["tokens"] == 85
    _, events = page.stream({"text": "Q4"})
    assert "compacting" not in kinds(events)
    sent = page.client.calls[4]
    assert sent[1:] == [f"{compression.SUMMARY_PREFIX}\nLaunch 14 November.", "Q2", "A2", "Q3", "A3", "Q4"]
    body = page.call("GET", "/api/context")[1]
    assert (body["last_tokens"], body["summaries"], body["saved"]) == (40, 1, 45)
    items = page.call("GET", "/api/session")[1]["items"]
    assert items[0]["text"].startswith(compression.SUMMARY_PREFIX)


def test_a_failed_summary_warns_and_keeps_the_history(web):
    page = start(web, [30, 50, 85], ["A1"], ["A2"], ["A3"], LLMError("down"), context_length=100)
    for question in ("Q1", "Q2"):
        page.stream({"text": question})
    _, events = page.stream({"text": "Q3"})
    warning = next(event for event in events if event["type"] == "warning")
    assert warning == {"type": "warning", "code": "context", "message": "The summary failed, full history kept."}
    assert events[-1] == {"type": "done", "status": "completed", "turn_id": events[0]["turn_id"]}
    assert len(page.call("GET", "/api/session")[1]["items"]) == 6


def test_compact_summarizes_on_demand(web):
    page = start(web, [30, 50, 200, 20], ["A1"], ["A2"], ["A3"], ["facts"])
    for question in ("x" * 400, "Q2", "Q3"):
        page.stream({"text": question})
    status, body = page.call("POST", "/api/context/compact", {})
    assert status == 200
    assert body["before"] == 200 and body["after"] == 109 and body["messages"] == 2 and body["summaries"] == 1
    assert page.call("GET", "/api/session")[1]["items"][0]["text"] == f"{compression.SUMMARY_PREFIX}\nfacts"


def test_compact_with_too_few_messages_is_refused(web):
    page = start(web, [10], ["A1"])
    page.stream({"text": "Q1"})
    status, body = page.call("POST", "/api/context/compact", {})
    assert status == 409 and body["error"]["code"] == "nothing_to_compact"


def test_a_new_session_restarts_the_counters(web):
    page = start(web, [30, 50, 60, 20], ["A1"], ["A2"], ["A3"], ["facts"])
    for question in ("Q1", "Q2", "Q3"):
        page.stream({"text": question})
    page.call("POST", "/api/context/compact", {})
    page.call("POST", "/api/sessions", {})
    body = page.call("GET", "/api/context")[1]
    assert (body["last_tokens"], body["summaries"], body["saved"]) == (None, 0, 0)


def test_the_page_follows_ollamas_choice_doubled(web, monkeypatch):
    from sensai_web import app as web_app
    monkeypatch.setattr(web_app, "ollama_window", lambda host, model: 4096)
    page = start(web, [], )
    body = page.call("GET", "/api/context")[1]
    assert (body["budget"], body["source"]) == (8192, "doubled")
    assert page.call("GET", "/api/config")[1]["context_length"] == 8192
