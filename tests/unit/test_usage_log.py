"""EV3: one log line per model call, and the statistics computed from the log."""
import json

import pytest

from fakes import FakeClient
from sensai import usage_log
from sensai.chat.session import ChatSession
from sensai.cli import main as cli
from sensai.cli.main import repl
from sensai.core.errors import LLMError


@pytest.fixture
def log(tmp_path, monkeypatch):
    path = tmp_path / "log.jsonl"
    monkeypatch.setattr(usage_log, "_path", str(path))
    return path


def lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def chat(client, inputs):
    session = ChatSession(client, "m", "Rules")
    feed = iter([*inputs, "exit"])
    repl(session, read=lambda _: next(feed), write=lambda text="", **_: None, meter=usage_log.Meter())


def test_each_turn_is_one_chat_line_with_its_answer_and_no_tools(log):
    chat(FakeClient(["Hello!"]), ["hi"])
    [line] = lines(log)
    assert (line["kind"], line["model"], line["question"], line["answer"], line["tools"], line["error"]) == (
        "chat", "m", "hi", "Hello!", [], None)


class Interrupted(FakeClient):
    def stream(self, model, messages, cancellation=None):
        if messages[-1].content == "and again":
            raise KeyboardInterrupt  # Ctrl+C while the reply streams.
        yield from super().stream(model, messages, cancellation)


def test_tool_calls_failures_and_cancelling_are_recorded(log):
    chat(Interrupted(['{"tool": "calculate", "arguments": {"expression": "6*7"}}'], ["42."], LLMError("connection refused")),
         ["six times seven?", "again", "and again"])
    first, failed, cancelled = lines(log)
    assert first["tools"] == [{"tool": "calculate", "input": '{"expression": "6*7"}', "ms": None, "ok": True}]
    assert failed["error"] == "connection refused" and failed["answer"] == ""
    assert cancelled["error"] == "cancelled"


def test_stats_count_calls_errors_tools_and_days():
    rows = [{"time": "2026-10-18T10:00:00+00:00", "kind": "chat", "latency_ms": 2000, "prompt_tokens": 100, "output_tokens": 20,
             "tools": [{"tool": "web_search", "ok": True}]},
            {"time": "2026-10-19T09:00:00+00:00", "kind": "chat", "latency_ms": 3000, "error": "connection refused",
             "tools": [{"tool": "web_search", "ok": False}]},
            {"time": "2026-10-19T09:01:00+00:00", "kind": "title", "latency_ms": 1000, "error": "cancelled"}]
    s = usage_log.stats(rows)
    assert (s["calls"], s["errors"], s["cancelled"], s["error_rate"], s["avg_latency_ms"]) == (3, 1, 1, 33, 2000)
    assert s["tools"] == {"web_search": {"calls": 2, "failed": 1}} and s["kinds"] == {"chat": 2, "title": 1}
    assert [(d["day"], d["calls"], d["errors"]) for d in s["days"]] == [("2026-10-18", 1, 0), ("2026-10-19", 2, 1)]
    text = usage_log.report(s)
    assert "Calls: 3   Errors: 1 (33%)" in text and "web_search 2 calls, 1 failed" in text and "2026-10-19" in text


def test_stats_without_a_model_or_a_log(tmp_path, monkeypatch, capsys, isolated_settings):
    monkeypatch.setenv("SENSAI_LOG", str(tmp_path / "none.jsonl"))
    cli.main(["--stats"])
    assert "No data yet" in capsys.readouterr().out
    (tmp_path / "none.jsonl").write_text('{"time": "2026-10-18T10:00:00+00:00", "kind": "chat", "latency_ms": 1500}\nnot json\n')
    cli.main(["--stats"])
    assert "Calls: 1" in capsys.readouterr().out  # A broken line is skipped.


def test_a_title_request_is_logged(log, real_titles):
    from sensai.chat.saved_sessions import generate_title
    generate_title(FakeClient(["Launch week"]), "m", "Plan the launch", "Sure.")
    assert lines(log)[0]["kind"] == "title" and lines(log)[0]["answer"] == "Launch week"


def test_a_reply_the_guardrails_blocked_is_a_refusal_not_an_error():
    s = usage_log.stats([{"time": "2026-10-18T10:00:00+00:00", "kind": "chat", "error": "blocked: unsupported_claim"},
                         {"time": "2026-10-18T10:01:00+00:00", "kind": "chat"}])
    assert (s["errors"], s["blocked"], s["error_rate"]) == (0, 1, 0)
