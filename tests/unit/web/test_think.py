"""/think over HTTP: step sections, tool rounds, approvals, the check, stop, timeout and saving."""
import threading

from fakes import FakeClient
from sensai.chat.reasoning import Check
from sensai.core.errors import LLMError
from sensai.llm.structured import StructuredOutputError

CALC = '{"tool": "calculate", "arguments": {"expression": "630 / 4200 * 100"}}'
PY = '{"tool": "run_python", "arguments": {"code": "print(6 * 7)"}}'
PROBLEM = '"cures eczema" is not an approved claim'


class FakeChecker:
    """Replays Check objects or raises; records each request."""

    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def complete(self, model, messages, schema):
        assert schema is Check
        self.calls.append(list(messages))
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


def thinking(web, *replies, checks=(Check(ok=True),), **overrides):
    page = web(*replies, **overrides)
    page.app.checker = FakeChecker(*checks)
    return page


def kinds(events):
    return [event["type"] for event in events]


def titles(events):
    return [event["title"] for event in events if event["type"] == "think_section"]


def shown(events):
    """The stream as the terminal would print it: [Title] lines and text."""
    return "".join(f"[{e['title']}]\n" if e["type"] == "think_section" else e["delta"]
                   for e in events if e["type"] in ("think_section", "text"))


def test_a_full_think_turn_streams_every_step_in_order(web):
    page = thinking(web, ["1. Compute the rate\n", "2. Write"], ["Computing.\n", CALC],
                    ["15% engaged. Cures eczema!"], ["15% engaged. Hydrates."],
                    checks=(Check(ok=False, problems=[PROBLEM]), Check(ok=True)))
    status, events = page.stream({"text": "Summarize the week", "mode": "think"})
    assert status == 200
    assert titles(events) == ["Plan", "Act", "Observe", "Draft", "Check — 1 problem", "Revise", "Check — ok",
                              "Final answer (2 rounds, 1 tool call)"]
    assert shown(events) == (
        "[Plan]\n1. Compute the rate\n2. Write\n"
        "Computing.\n[Act]\ncalculate({\"expression\":\"630 / 4200 * 100\"})\n[Observe]\n15.0\n"
        "[Draft]\n15% engaged. Cures eczema!\n"
        f"[Check — 1 problem]\n- {PROBLEM}\n"
        "[Revise]\n15% engaged. Hydrates.\n[Check — ok]\n"
        "[Final answer (2 rounds, 1 tool call)]\n15% engaged. Hydrates.\n")
    assert kinds(events)[0] == "turn_start" and kinds(events)[-5:] == ["think_done", "usage", "saved", "title", "done"]
    assert events[-5] == {"type": "think_done", "answer": "15% engaged. Hydrates.", "rounds": 2, "tool_calls": 1,
                          "unresolved": [], "checked": True}
    assert events[-1]["status"] == "completed"
    assert len(page.app.checker.calls) == 2 and "15.0" in page.app.checker.calls[0][1].content


def test_each_tool_round_has_one_call_and_one_result_before_its_act_step(web):
    page = thinking(web, ["Plan"], [CALC], ["Done."])
    _, events = page.stream({"text": "rate?", "mode": "think"})
    assert kinds(events).count("tool_call") == 1 and kinds(events).count("tool_result") == 1
    call = kinds(events).index("tool_call")
    act = next(i for i, e in enumerate(events) if e.get("title") == "Act")
    assert kinds(events)[call:act] == ["tool_call", "tool_result"]
    assert events[call]["round"] == 1 and events[call + 1]["output"] == "15.0"


def test_an_unparsable_tool_block_still_shows_as_a_failed_call_before_its_act_step(web):
    page = thinking(web, ["Plan"], ['{"tool": 7}'], ["Sorry."])
    _, events = page.stream({"text": "x", "mode": "think"})
    call = kinds(events).index("tool_call")
    assert events[call]["name"] == "<invalid>" and events[call + 1]["ok"] is False
    assert events[call + 2] == {"type": "think_section", "title": "Act"}


def test_run_python_still_asks_inside_a_think_turn(web):
    page = thinking(web, ["Plan"], [PY], ["It is 42."])

    def on_event(event):
        if event["type"] == "approval_request":
            assert event["action"] == "run_python" and event["call_id"] == "c1"
            page.call("POST", f"/api/approvals/{event['id']}", {"approved": True})

    _, events = page.stream({"text": "6*7?", "mode": "think"}, on_event)
    start = kinds(events).index("tool_call")
    assert kinds(events)[start:start + 5] == ["tool_call", "approval_request", "approval_result", "tool_result",
                                              "think_section"]
    assert events[start + 3]["ok"] is True and events[start + 3]["meta"]["stdout"] == "42\n"
    assert events[-1]["status"] == "completed"


def test_a_refused_run_is_the_observation(web):
    page = thinking(web, ["Plan"], [PY], ["No code, then."])

    def on_event(event):
        if event["type"] == "approval_request":
            page.call("POST", f"/api/approvals/{event['id']}", {"approved": False})

    _, events = page.stream({"text": "go", "mode": "think"}, on_event)
    assert "[Observe]\ntool approval refused\n" in shown(events)
    assert next(e for e in events if e["type"] == "think_done")["answer"] == "No code, then."


def test_only_the_request_and_the_final_answer_are_kept_and_saved(web):
    page = thinking(web, ["Plan"], [CALC], ["Draft one"], ["Final one"], ["Shorter."],
                    checks=(Check(ok=False, problems=["too long"]), Check(ok=True)))
    page.stream({"text": "Summarize", "mode": "think"})
    session = page.call("GET", "/api/session")[1]
    assert [(i["kind"], i["text"]) for i in session["items"]] == [("user", "Summarize"), ("assistant", "Final one")]
    assert session["items"][1]["tools"] == [] and session["saved"] is True
    stored = page.call("GET", f"/api/sessions/{session['id']}")[1]
    assert [i["text"] for i in stored["items"]] == ["Summarize", "Final one"]
    assert page.call("GET", "/api/history")[1]["items"] == [{"n": 1, "text": "Summarize"}]
    page.stream({"text": "make it shorter"})
    assert page.client.calls[-1][1:] == ["Summarize", "Final one", "make it shorter"]


def test_exhausted_checks_list_the_unresolved_problems(web):
    page = thinking(web, ["Plan"], ["A"], ["B"], ["C"],
                    checks=(Check(ok=False, problems=["p1"]), Check(ok=False, problems=["p2"]),
                            Check(ok=False, problems=["p3"])))
    _, events = page.stream({"text": "x", "mode": "think"})
    assert titles(events)[-2:] == ["Unresolved", "Final answer (3 rounds, 0 tool calls)"]
    done = next(e for e in events if e["type"] == "think_done")
    assert (done["answer"], done["unresolved"], done["checked"]) == ("C", ["p3"], True)


def test_an_invalid_check_reply_ends_unchecked(web):
    page = thinking(web, ["Plan"], ["Answer"], checks=(StructuredOutputError("bad json"),))
    _, events = page.stream({"text": "x", "mode": "think"})
    assert "Check unavailable" in titles(events)
    done = next(e for e in events if e["type"] == "think_done")
    assert (done["answer"], done["checked"]) == ("Answer", False) and events[-1]["status"] == "completed"


def test_a_failing_check_is_an_error_and_nothing_is_kept(web):
    page = thinking(web, ["Plan"], ["Answer"], ["after"], checks=(LLMError("Ollama at x timed out"),))
    _, events = page.stream({"text": "x", "mode": "think"})
    assert events[-1]["type"] == "error" and "done" not in kinds(events) and "think_done" not in kinds(events)
    assert page.call("GET", "/api/session")[1]["items"] == []
    assert page.app.turn is None
    _, events = page.stream({"text": "next"})
    assert events[-1]["status"] == "completed"


class SlowPlan(FakeClient):
    """Streams one chunk of the plan, then waits until cancelled (or a few seconds pass)."""

    def __init__(self, started: threading.Event, *replies):
        super().__init__(*replies)
        self.started = started
        self.slow = True

    def stream(self, model, messages, cancellation=None):
        if not self.slow:
            yield from super().stream(model, messages, cancellation)
            return
        self.slow = False
        yield "1. "
        self.started.set()
        for _ in range(100):
            cancellation.raise_if_cancelled()
            threading.Event().wait(0.05)
        yield "late"


def test_stop_during_a_step_interrupts_and_keeps_nothing(web):
    started = threading.Event()
    page = web(client=SlowPlan(started, ["after the stop"]))
    page.app.checker = FakeChecker()
    stopper = threading.Thread(target=lambda: (started.wait(5), page.call("POST", "/api/chat/stop")))
    stopper.start()
    _, events = page.stream({"text": "long", "mode": "think"})
    stopper.join()
    assert events[-1] == {"type": "done", "status": "interrupted", "turn_id": events[0]["turn_id"]}
    assert "saved" not in kinds(events) and "think_done" not in kinds(events)
    assert page.call("GET", "/api/session")[1]["items"] == []
    assert page.app.turn is None and page.app.checker.calls == []
    _, events = page.stream({"text": "next"})
    assert events[-1]["status"] == "completed"
    assert page.client.calls[-1][1:] == ["next"]


def test_stop_while_an_approval_waits_interrupts_the_think_turn(web):
    page = thinking(web, ["Plan"], [PY])

    def on_event(event):
        if event["type"] == "approval_request":
            page.call("POST", "/api/chat/stop")

    _, events = page.stream({"text": "go", "mode": "think"}, on_event)
    assert events[-1]["status"] == "interrupted"
    assert page.call("GET", "/api/session")[1]["items"] == []


def test_a_step_past_the_budget_times_out_and_keeps_nothing(web):
    page = web(client=SlowPlan(threading.Event()), operation_timeout=0.3)
    page.app.checker = FakeChecker()
    _, events = page.stream({"text": "slow", "mode": "think"})
    assert events[-1]["status"] == "timed_out" and "saved" not in kinds(events)
    assert page.call("GET", "/api/session")[1]["items"] == []
    assert page.app.turn is None


class Steady(FakeClient):
    """Each reply takes 0.2 s: one step fits the budget, the whole turn does not."""

    def stream(self, model, messages, cancellation=None):
        threading.Event().wait(0.2)
        cancellation.raise_if_cancelled()
        yield from super().stream(model, messages, cancellation)


def test_each_step_gets_its_own_budget(web):
    page = web(client=Steady(["Plan"], ["Done."]), operation_timeout=0.35)
    page.app.checker = FakeChecker(Check(ok=True))
    _, events = page.stream({"text": "rate?", "mode": "think"})
    assert events[-1]["status"] == "completed" and len(page.client.calls) >= 2


def test_the_check_client_uses_the_chat_host_and_the_step_budget(web):
    page = web(host="http://127.0.0.1:11435", operation_timeout=42.0, context_length=8192)
    checker = page.app.checker
    assert (checker.host, checker.timeout, checker.context_length) == ("http://127.0.0.1:11435", 42.0, 8192)


def test_think_text_is_validated_like_a_normal_message(web):
    page = thinking(web)
    for body in ({"text": "", "mode": "think"}, {"text": "  ", "mode": "think"}, {"mode": "think"}):
        status, payload = page.stream(body)
        assert status == 400 and payload["error"]["code"] == "empty_input"
    for mode in ("deep", 1, [], {"a": 1}):
        status, payload = page.stream({"text": "hi", "mode": mode})
        assert status == 400 and payload["error"]["code"] == "bad_request"
    assert page.app.turn is None


def test_normal_turns_are_unchanged_with_or_without_the_mode(web):
    page = thinking(web, ["one"], ["two"])
    for body in ({"text": "a"}, {"text": "b", "mode": "normal"}):
        _, events = page.stream(body)
        assert "think_section" not in kinds(events) and "think_done" not in kinds(events)
        assert events[-1]["status"] == "completed"
    assert page.app.checker.calls == []


def test_only_one_turn_runs_at_a_time_in_think_mode(web):
    started = threading.Event()
    page = web(client=SlowPlan(started))
    page.app.checker = FakeChecker()
    holder = threading.Thread(target=lambda: page.stream({"text": "first", "mode": "think"}))
    holder.start()
    assert started.wait(5)
    status, body = page.stream({"text": "second", "mode": "think"})
    assert status == 429 and body["error"]["code"] == "busy"
    page.call("POST", "/api/chat/stop")
    holder.join()


def test_the_config_reports_the_think_capability(web):
    assert web().call("GET", "/api/config")[1]["capabilities"]["think"] is True
