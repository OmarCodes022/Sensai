"""Chat turns over HTTP: streaming, tool calls, approval, stop, saving and sessions."""
import threading

import pytest

from fakes import FakeClient
from sensai.core.cancellation import CancellationToken
from sensai.llm.ollama_api import OllamaUsage
from sensai_web import app as web_app

CALC = '{"tool": "calculate", "arguments": {"expression": "630 / 4200 * 100"}}'
PY = '{"tool": "run_python", "arguments": {"code": "print(6 * 7)"}}'


def kinds(events):
    return [event["type"] for event in events]


def text(events):
    return "".join(event["delta"] for event in events if event["type"] == "text")


def test_a_turn_streams_text_then_usage_save_and_done(web):
    page = web(["Hel", "lo ", "there"])
    status, events = page.stream({"text": "hi"})
    assert status == 200
    assert kinds(events) == ["turn_start", "text", "text", "text", "usage", "saved", "title", "done"]
    assert events[0]["model"] == "fake" and events[0]["number"] == 1 and events[0]["budget_seconds"] == 30
    assert text(events) == "Hello there"
    assert events[-1]["status"] == "completed" and events[-1]["turn_id"] == events[0]["turn_id"]
    assert events[-4]["prompt_tokens"] is None  # The scripted client reports no token counts.


def test_the_reply_is_in_the_session_the_history_and_the_list(web):
    page = web(["First answer"], ["Second answer"])
    page.stream({"text": "first question"})
    page.stream({"text": "second question\nwith detail"})
    session = page.call("GET", "/api/session")[1]
    assert session["saved"] is True and session["title"] == "first question"
    assert [(i["kind"], i["text"]) for i in session["items"]] == [
        ("user", "first question"), ("assistant", "First answer"),
        ("user", "second question\nwith detail"), ("assistant", "Second answer")]
    assert session["usage"]["turns"] == 2
    assert page.call("GET", "/api/history")[1]["items"] == [
        {"n": 1, "text": "first question"}, {"n": 2, "text": "second question …"}]
    listed = page.call("GET", "/api/sessions")[1]["items"]
    assert [(s["id"], s["title"], s["messages"]) for s in listed] == [(session["id"], "first question", 4)]


def test_the_conversation_is_sent_to_the_model_in_order(web):
    page = web(["a1"], ["a2"])
    page.stream({"text": "q1"})
    page.stream({"text": "q2"})
    contents = page.client.calls[1]
    assert contents[1:] == ["q1", "a1", "q2"] and "calculate" in contents[0]


def test_empty_text_is_refused_before_a_turn_starts(web):
    page = web()
    for body in ({"text": ""}, {"text": "   "}, {"text": 5}, {}):
        status, payload = page.stream(body)
        assert status == 400 and payload["error"]["code"] == "empty_input"


def test_a_turn_reports_usage_from_ollama(web):
    sinks = []

    class Reporting(FakeClient):
        def stream(self, model, messages, cancellation=None):
            yield from super().stream(model, messages, cancellation)
            sinks[0](OllamaUsage(prompt_tokens=120, output_tokens=30, latency_ms=900.4, server_duration_ms=800.0))

    import sensai_web.app as module
    page = web(client=Reporting(["ok"]))
    sinks.append(page.app.usage.add)
    _, events = page.stream({"text": "hi"})
    usage = next(event for event in events if event["type"] == "usage")
    assert usage == {"type": "usage", "prompt_tokens": 120, "output_tokens": 30, "latency_ms": 900,
                     "server_duration_ms": 800.0}
    assert page.call("GET", "/api/session")[1]["usage"] == {
        "prompt_tokens": 120, "output_tokens": 30, "turns": 1, "last_prompt_tokens": 120}
    assert module is web_app


def test_the_calculator_runs_and_the_answer_follows(web):
    page = web([f"Let me check.\n{CALC}"], ["It is 15.0%."])
    _, events = page.stream({"text": "rate?"})
    assert kinds(events) == ["turn_start", "text", "tool_call", "tool_result", "text", "usage", "saved", "title", "done"]
    call, result = events[2], events[3]
    assert call == {"type": "tool_call", "id": "c1", "name": "calculate", "round": 1,
                    "arguments": {"expression": "630 / 4200 * 100"}}
    assert (result["id"], result["ok"], result["output"], result["error"]) == ("c1", True, "15.0", None)
    assert text(events) == "Let me check.\nIt is 15.0%."
    item = page.call("GET", "/api/session")[1]["items"][1]
    assert item["text"] == "Let me check.\nIt is 15.0%."
    assert item["tools"][0]["output"] == "15.0" and item["tools"][0]["ok"] is True


def test_a_failing_tool_is_reported_and_the_model_answers_anyway(web):
    bad = '{"tool": "calculate", "arguments": {"expression": "1/0"}}'
    page = web([bad], ["Cannot divide by zero."])
    _, events = page.stream({"text": "x"})
    result = next(e for e in events if e["type"] == "tool_result")
    assert result["ok"] is False and "ZeroDivisionError" in result["error"]
    assert events[-1]["status"] == "completed"


def test_an_unparsable_or_unknown_tool_block_still_shows_as_a_failed_call(web):
    page = web(['{"tool": "teleport", "arguments": {}}'], ["Sorry."], ['{"tool": 7}'], ["Sorry."])
    _, events = page.stream({"text": "x"})
    result = next(e for e in events if e["type"] == "tool_result")
    assert (result["name"], result["ok"], result["error"]) == ("teleport", False, "unknown tool")
    _, events = page.stream({"text": "y"})
    result = next(e for e in events if e["type"] == "tool_result")
    assert result["name"] == "<invalid>" and result["ok"] is False


def test_run_python_waits_for_approval_then_runs(web):
    page = web([f"Computing.\n{PY}"], ["It is 42."])
    seen = []

    def on_event(event):
        seen.append(event["type"])
        if event["type"] == "approval_request":
            assert event["action"] == "run_python" and event["call_id"] == "c1"
            assert "reason" not in event  # The page words it in its own language.
            assert event["preview"]["lines"] == [{"header": "code:", "text": "print(6 * 7)"}]
            assert page.call("POST", f"/api/approvals/{event['id']}", {"approved": True}) == (200, {"ok": True})

    _, events = page.stream({"text": "6*7?"}, on_event)
    assert kinds(events) == ["turn_start", "text", "tool_call", "approval_request", "approval_result", "tool_result",
                             "text", "usage", "saved", "title", "done"]
    assert events[4]["approved"] is True
    result = events[5]
    assert result["ok"] is True and "42" in result["output"]
    assert result["meta"]["stdout"] == "42\n" and result["meta"]["exit_code"] == 0
    assert result["meta"]["limits"]["wall_seconds"] == 15 and "report" not in result["meta"]


def test_a_refused_run_never_executes_and_the_model_is_told(web):
    page = web([f"Computing.\n{PY}"], ["Understood, no code."])

    def on_event(event):
        if event["type"] == "approval_request":
            page.call("POST", f"/api/approvals/{event['id']}", {"approved": False})

    _, events = page.stream({"text": "go"}, on_event)
    assert next(e for e in events if e["type"] == "approval_result")["approved"] is False
    result = next(e for e in events if e["type"] == "tool_result")
    assert (result["ok"], result["error"]) == (False, "tool approval refused") and "meta" not in result
    assert "Tool error from run_python:\nAttempt 1 of 3 · tool approval refused" in page.client.calls[1][-1]
    item = page.call("GET", "/api/session")[1]["items"][1]
    assert item["tools"][0]["refused"] is True


def test_the_approval_prompt_escapes_hidden_characters(web):
    hostile = '{"tool": "run_python", "arguments": {"code": "print(1)\\u202e\\u001b[2J"}}'
    page = web([hostile], ["done"])

    def on_event(event):
        if event["type"] == "approval_request":
            assert "‮" not in event["preview"]["lines"][0]["text"]
            assert "\\u202e" in event["preview"]["lines"][0]["text"]
            page.call("POST", f"/api/approvals/{event['id']}", {"approved": False})

    page.stream({"text": "go"}, on_event)


def test_a_long_script_preview_is_cut_and_marked_incomplete(web):
    code = "\\n".join(f"x{i} = {i}" for i in range(10))
    page = web([f'{{"tool": "run_python", "arguments": {{"code": "{code}"}}}}'], ["done"])
    previews = []

    def on_event(event):
        if event["type"] == "approval_request":
            previews.append(event["preview"])
            page.call("POST", f"/api/approvals/{event['id']}", {"approved": False})

    page.stream({"text": "go"}, on_event)
    assert len(previews[0]["lines"]) == 6 and previews[0]["hidden_lines"] == 4 and previews[0]["incomplete"] is True


def test_stop_interrupts_a_waiting_approval_and_leaves_no_trace(web):
    page = web([PY])
    outcome = {}

    def on_event(event):
        if event["type"] == "approval_request":
            outcome["stop"] = page.call("POST", "/api/chat/stop")[1]

    _, events = page.stream({"text": "go"}, on_event)
    assert outcome["stop"] == {"stopped": True}
    assert kinds(events)[-2:] == ["approval_result", "done"] and events[-1]["status"] == "interrupted"
    assert events[-2]["approved"] is False
    assert page.call("GET", "/api/session")[1]["items"] == []
    assert page.call("GET", "/api/sessions")[1]["items"] == []


class Slow(FakeClient):
    """Streams one chunk, then waits until the turn is cancelled (or a few seconds pass)."""

    def __init__(self, started: threading.Event):
        super().__init__()
        self.started = started

    def stream(self, model, messages, cancellation: CancellationToken | None = None):
        yield "partial "
        self.started.set()
        for _ in range(100):
            cancellation.raise_if_cancelled()
            threading.Event().wait(0.05)
        yield "late"


def test_stop_ends_a_streaming_reply_as_interrupted_and_nothing_is_saved(web):
    started = threading.Event()
    page = web(client=Slow(started))
    stopper = threading.Thread(target=lambda: (started.wait(5), page.call("POST", "/api/chat/stop")))
    stopper.start()
    _, events = page.stream({"text": "long one"})
    stopper.join()
    assert events[-1] == {"type": "done", "status": "interrupted", "turn_id": events[0]["turn_id"]}
    assert text(events) == "partial " and "saved" not in kinds(events)
    assert page.call("GET", "/api/session")[1]["items"] == []


def test_the_turn_budget_ends_a_slow_reply_as_timed_out(web):
    page = web(client=Slow(threading.Event()), operation_timeout=0.3)
    _, events = page.stream({"text": "slow"})
    assert events[-1]["status"] == "timed_out" and events[0]["budget_seconds"] == 0.3
    assert page.call("GET", "/api/session")[1]["items"] == []


def test_only_one_turn_runs_at_a_time(web):
    started = threading.Event()
    page = web(client=Slow(started))
    holder = threading.Thread(target=lambda: page.stream({"text": "first"}))
    holder.start()
    assert started.wait(5)
    status, body = page.stream({"text": "second"})
    assert status == 429 and body["error"]["code"] == "busy"
    assert page.call("POST", "/api/sessions")[0] == 429
    assert page.call("POST", "/api/persona", {"id": "analyse"})[0] == 429
    assert page.call("PUT", "/api/profile", {"preferences": {"a": "b"}})[0] == 429
    page.call("POST", "/api/chat/stop")
    holder.join()


def test_sessions_can_be_started_listed_and_resumed(web):
    page = web(["Answer one"], ["Answer two"])
    page.stream({"text": "about serum"})
    first = page.call("GET", "/api/session")[1]["id"]
    fresh = page.call("POST", "/api/sessions")[1]
    assert fresh["id"] != first and fresh["items"] == [] and fresh["saved"] is False
    page.stream({"text": "about cream"})
    second = page.call("GET", "/api/session")[1]["id"]
    listed = page.call("GET", "/api/sessions")[1]["items"]
    assert {s["id"]: s["title"] for s in listed} == {first: "about serum", second: "about cream"}
    other = page.call("GET", f"/api/sessions/{first}")[1]
    assert [i["text"] for i in other["items"]] == ["about serum", "Answer one"]
    assert page.call("GET", "/api/session")[1]["id"] == second  # Reading does not switch.
    resumed = page.call("POST", f"/api/sessions/{first}/resume")[1]
    assert resumed["id"] == first and resumed["saved"] is True and resumed["title"] == "about serum"
    assert page.call("GET", "/api/history")[1]["items"] == [{"n": 1, "text": "about serum"}]


def test_a_resumed_session_continues_with_its_full_history(web):
    page = web(["a1"], ["a2"])
    page.stream({"text": "q1"})
    sid = page.call("GET", "/api/session")[1]["id"]
    page.call("POST", "/api/sessions")
    page.call("POST", f"/api/sessions/{sid}/resume")
    page.stream({"text": "q2"})
    assert page.client.calls[1][1:] == ["q1", "a1", "q2"]
    assert [i["text"] for i in page.call("GET", f"/api/sessions/{sid}")[1]["items"]] == ["q1", "a1", "q2", "a2"]


def test_a_session_resumes_after_a_restart_with_its_persona(web, tmp_path):
    page = web(["a1"])
    page.call("POST", "/api/persona", {"id": "analyse"})
    page.stream({"text": "q1"})
    sid = page.call("GET", "/api/session")[1]["id"]
    again = web(session=sid)
    session = again.call("GET", "/api/session")[1]
    assert (session["id"], session["persona"], session["saved"]) == (sid, "analyse", True)
    assert [i["text"] for i in session["items"]] == ["q1", "a1"]


def test_changing_persona_in_a_saved_session_is_saved(web):
    page = web(["a1"])
    page.stream({"text": "q1"})
    sid = page.call("GET", "/api/session")[1]["id"]
    page.call("POST", "/api/persona", {"id": "communaute"})
    assert page.call("GET", "/api/sessions")[1]["items"][0]["persona"] == "communaute"
    assert page.call("POST", f"/api/sessions/{sid}/resume")[1]["persona"] == "communaute"


def test_a_new_session_keeps_the_chosen_persona(web):
    page = web()
    page.call("POST", "/api/persona", {"id": "analyse"})
    assert page.call("POST", "/api/sessions")[1]["persona"] == "analyse"


def test_sessions_of_another_creator_are_not_visible(web, tmp_path):
    amy = web(["a1"], creator="amy")
    amy.stream({"text": "private"})
    ben = web(creator="ben")
    assert ben.call("GET", "/api/sessions")[1]["items"] == []
    sid = amy.call("GET", "/api/session")[1]["id"]
    assert ben.call("GET", f"/api/sessions/{sid}")[0] == 404


def test_an_unknown_session_or_persona_at_startup_is_a_clear_error(web):
    with pytest.raises(web_app.StartupError, match="unknown session: nope"):
        web(session="nope")
    with pytest.raises(web_app.StartupError, match="unknown persona: nope"):
        web(persona="nope")


def test_the_run_endpoint_runs_code_and_reports_the_result(web):
    page = web()
    status, body = page.call("POST", "/api/run", {"code": "print(sum(range(10)))"})
    assert status == 200 and body["stdout"] == "45\n" and body["exit_code"] == 0
    assert body["timed_out"] is False and body["truncated"] is False
    assert body["report"].startswith("Exit code 0") and body["limits"]["memory_mb"] == 512
    status, body = page.call("POST", "/api/run", {"code": "import sys\nsys.stderr.write('bad')\nsys.exit(3)"})
    assert (body["exit_code"], body["stderr"]) == (3, "bad")


def test_the_run_endpoint_rejects_bad_code_arguments(web):
    page = web()
    assert page.call("POST", "/api/run", {"code": "  "})[1]["error"]["code"] == "empty_code"
    assert page.call("POST", "/api/run", {})[0] == 400
    assert page.call("POST", "/api/run", {"code": 5})[0] == 400
    assert page.call("POST", "/api/run", {"code": "x" * (1024 * 1024 + 1)})[0] == 413


def test_the_data_folder_is_listed_and_visible_to_runs(web, tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "figures.csv").write_text("a,b\n1,2\n")
    (data / "evil.py").write_text("print('no')")
    page = web(data_dir=str(data))
    listing = page.call("GET", "/api/run/data")[1]
    assert (listing["dir"], listing["exists"], listing["files"]) == (str(data), True, [{"name": "figures.csv", "bytes": 8}])
    body = page.call("POST", "/api/run", {"code": "print(open('figures.csv').read().strip())"})[1]
    assert body["stdout"] == "a,b\n1,2\n"


def test_a_missing_data_folder_stops_the_server_from_starting(web, tmp_path):
    with pytest.raises(web_app.StartupError, match="data folder not found"):
        web(data_dir=str(tmp_path / "missing"))
