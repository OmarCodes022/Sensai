"""Review of /think in the web page: stops and timeouts at every step, the event order the page relies on,
the locks and approvals left behind, and the string inventory."""
import json
import re
import threading
from pathlib import Path

import pytest

from fakes import FakeClient
from sensai.chat.reasoning import Check
from sensai.core.ports import ToolResult
from sensai.tools import ToolDefinition
from sensai_web import turn as web_turn
from sensai_web.tools import ObservedRegistry

CALC = '{"tool": "calculate", "arguments": {"expression": "630 / 4200 * 100"}}'
CALC2 = '{"tool": "calculate", "arguments": {"expression": "2 * 3"}}'
BLANK = '{"tool": "blank", "arguments": {}}'
PY = '{"tool": "run_python", "arguments": {"code": "print(6 * 7)"}}'
SLEEPY = '{"tool": "run_python", "arguments": {"code": "import time\\ntime.sleep(20)"}}'
STATIC = Path(__file__).resolve().parents[3] / "web" / "sensai_web" / "static"
SPEC = Path(__file__).resolve().parents[3] / "web" / "web-ui.md"


class FakeChecker:
    """Replays Check objects (or callables run before answering); records each request."""

    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def complete(self, model, messages, schema):
        self.calls.append(list(messages))
        result = self.results.pop(0)
        if callable(result):
            result = result()
        if isinstance(result, BaseException):
            raise result
        return result


class Gated(FakeClient):
    """Plays scripted replies; reply number `slow_at` (0-based) waits until cancelled or `wait` seconds pass."""

    def __init__(self, *replies, slow_at, wait=5.0):
        super().__init__(*replies)
        self.slow_at, self.wait = slow_at, wait
        self.started = threading.Event()
        self.count = 0

    def stream(self, model, messages, cancellation=None):
        index, self.count = self.count, self.count + 1
        if index != self.slow_at:
            yield from super().stream(model, messages, cancellation)
            return
        self.calls.append([m.content for m in messages])
        yield "slow "
        self.started.set()
        for _ in range(int(self.wait / 0.05)):
            cancellation.raise_if_cancelled()
            threading.Event().wait(0.05)
        yield "late"


def kinds(events):
    return [event["type"] for event in events]


def think_page(web, *replies, checks=(Check(ok=True),), client=None, **overrides):
    page = web(*replies, client=client, **overrides) if client else web(*replies, **overrides)
    page.app.checker = FakeChecker(*checks)
    return page


def assert_nothing_kept_and_idle(page, events):
    assert "think_done" not in kinds(events) and "saved" not in kinds(events)
    session = page.call("GET", "/api/session")[1]
    assert session["items"] == [] and session["saved"] is False
    assert page.app.turn is None
    assert page.app.approvals._pending == {}


# --- stops and timeouts at each step -------------------------------------------------------------------------


def test_stop_during_the_check_interrupts_once_the_check_returns_and_keeps_nothing(web):
    page = think_page(web, ["Plan"], ["Answer"], ["after"])
    page.app.checker = FakeChecker(lambda: (page.app.stop_turn(), Check(ok=True))[1])
    _, events = page.stream({"text": "x", "mode": "think"})
    assert events[-1]["type"] == "done" and events[-1]["status"] == "interrupted"
    assert "Check — ok" not in [e.get("title") for e in events]
    assert_nothing_kept_and_idle(page, events)
    _, events = page.stream({"text": "next"})
    assert events[-1]["status"] == "completed" and page.client.calls[-1][1:] == ["next"]


def test_stop_during_the_revise_step_keeps_nothing(web):
    client = Gated(["Plan"], ["Draft"], slow_at=2)
    page = think_page(web, client=client, checks=(Check(ok=False, problems=["fix it"]),))
    threading.Thread(target=lambda: (client.started.wait(5), page.call("POST", "/api/chat/stop")), daemon=True).start()
    _, events = page.stream({"text": "x", "mode": "think"})
    assert [e["title"] for e in events if e["type"] == "think_section"][-1] == "Check — 1 problem"
    assert events[-1]["status"] == "interrupted"
    assert_nothing_kept_and_idle(page, events)


def test_the_revise_step_has_its_own_budget_and_times_out_alone(web):
    client = Gated(["Plan"], ["Draft"], slow_at=2)
    page = think_page(web, client=client, checks=(Check(ok=False, problems=["fix it"]),), operation_timeout=0.4)
    _, events = page.stream({"text": "x", "mode": "think"})
    assert events[-1]["status"] == "timed_out"
    assert "Check — 1 problem" in [e.get("title") for e in events]
    assert_nothing_kept_and_idle(page, events)


def test_stop_while_run_python_runs_interrupts_sweeps_and_keeps_nothing(web, monkeypatch):
    swept = []
    real = web_turn.remove_stale_folders
    monkeypatch.setattr(web_turn, "remove_stale_folders", lambda: (swept.append(1), real()))
    page = think_page(web, ["Plan"], [SLEEPY], ["unused"])

    def on_event(event):
        if event["type"] == "approval_request":
            page.call("POST", f"/api/approvals/{event['id']}", {"approved": True})
        elif event["type"] == "approval_result":
            threading.Timer(0.5, lambda: page.call("POST", "/api/chat/stop")).start()

    _, events = page.stream({"text": "x", "mode": "think"}, on_event)
    assert events[-1]["status"] == "interrupted"
    assert "tool_result" not in kinds(events) and "Act" not in [e.get("title") for e in events]
    assert swept == [1]
    assert_nothing_kept_and_idle(page, events)
    _, events = page.stream({"text": "next"})
    assert events[-1]["status"] == "completed"


def test_stop_while_an_approval_waits_leaves_no_pending_approval(web):
    page = think_page(web, ["Plan"], [PY])

    def on_event(event):
        if event["type"] == "approval_request":
            assert page.app.approvals._pending  # it is waiting here
            page.call("POST", "/api/chat/stop")

    _, events = page.stream({"text": "go", "mode": "think"}, on_event)
    assert kinds(events)[-2:] == ["approval_result", "done"] and events[-2]["approved"] is False
    assert_nothing_kept_and_idle(page, events)


def test_a_normal_message_or_a_persona_switch_during_a_think_turn_is_busy(web):
    client = Gated(slow_at=0)
    page = think_page(web, client=client)
    holder = threading.Thread(target=lambda: page.stream({"text": "first", "mode": "think"}))
    holder.start()
    assert client.started.wait(5)
    status, body = page.stream({"text": "second"})
    assert status == 429 and body["error"]["code"] == "busy"
    assert page.call("POST", "/api/persona", {"id": "analyse"})[0] == 429
    assert page.call("POST", "/api/sessions")[0] == 429
    page.call("POST", "/api/chat/stop")
    holder.join()
    assert page.app.turn is None


# --- the event order the page's "one rendering per round" rule relies on ------------------------------------


def _blank(arguments, cancellation=None):
    return ToolResult("")


class WithBlank(ObservedRegistry):
    """The turn's registry plus a tool whose output is empty."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.register(ToolDefinition("blank", "Returns nothing.", {"type": "object", "properties": {}}),
                      _blank, timeout=None)


class PageMirror:
    """reasoning.js + the think branches of turn.js, line for line (section / text / addTool / think_done)."""

    def __init__(self):
        self.steps, self.body = [], ""
        self.current = self.pending = self.act = None
        self.skip = self.final = False

    def _step(self, kind):
        step = {"kind": kind, "text": "", "card": None}
        self.steps.append(step)
        return step

    def feed(self, event):
        kind = event["type"]
        if kind == "think_section":
            title = event["title"]
            named = {"Plan": "plan", "Act": "act", "Observe": "observe", "Draft": "draft", "Revise": "revise",
                     "Unresolved": "unresolved", "Check unavailable": "unavailable"}
            step_kind = named.get(title) or ("ok" if title == "Check — ok" else "problems" if title.startswith("Check — ")
                                             else "final" if title.startswith("Final answer (") else "other")
            if step_kind == "final":
                self.final, self.current, self.skip = True, None, False
                return
            if step_kind == "act" and self.pending:
                self.current = self.act = self.pending
                self.pending = None
            else:
                self.current = self._step(step_kind)
                if step_kind == "act":
                    self.act = self.current
            card = self.act["card"] if step_kind in ("act", "observe") and self.act else None
            self.skip = bool(card)
        elif kind == "text":
            if self.final or not self.current:
                self.body += event["delta"]
            elif self.skip:
                self.skip = False
            else:
                self.current["text"] += event["delta"]
        elif kind == "tool_call":
            self.pending = self._step("act")
            self.pending["card"] = event["name"]
        elif kind == "think_done":
            self.body = event["answer"]


def test_every_act_and_observe_section_is_followed_by_exactly_one_text_event(web, monkeypatch):
    """Narration without a newline, two rounds back to back, an unparsable block, an empty tool output."""
    monkeypatch.setattr(web_turn, "ObservedRegistry", WithBlank)
    page = think_page(web, ["1. one\n2. two"], ["Let me compute  \n", CALC], [CALC2], ['{"tool": 7}'],
                      ["Nothing to see.\n", BLANK], ["The rate is 15%."])
    _, events = page.stream({"text": "rate?", "mode": "think"})
    assert events[-1]["status"] == "completed"
    for i, event in enumerate(events):
        if event["type"] == "think_section" and event["title"] in ("Act", "Observe"):
            assert events[i + 1]["type"] == "text" and events[i + 2]["type"] != "text", events[i:i + 3]
    observe_lines = [events[i + 1]["delta"] for i, e in enumerate(events) if e.get("title") == "Observe"]
    assert observe_lines[-1] == "\n"  # an empty output still has its line, so the page drops that and only that


def test_the_page_rule_keeps_every_narration_and_answer_line_and_shows_each_round_once(web, monkeypatch):
    monkeypatch.setattr(web_turn, "ObservedRegistry", WithBlank)
    page = think_page(web, ["1. one\n2. two"], ["Let me compute  \n", CALC], [CALC2], ['{"tool": 7}'],
                      ["Nothing to see.\n", BLANK], ["The rate is 15%."],
                      checks=(Check(ok=False, problems=["say where 15% comes from"]), Check(ok=True)))
    page.client.replies.append(["15% (630 of 4,200)."])
    _, events = page.stream({"text": "rate?", "mode": "think"})
    mirror = PageMirror()
    for event in events:
        mirror.feed(event)
    shown = [(s["kind"], s["text"], s["card"]) for s in mirror.steps]
    assert shown == [
        ("plan", "1. one\n2. two\nLet me compute  \n", None),
        ("act", "", "calculate"), ("observe", "", None),
        ("act", "", "calculate"), ("observe", "", None),
        ("act", "", "<invalid>"), ("observe", "Nothing to see.\n", None),
        ("act", "", "blank"), ("observe", "", None),
        ("draft", "The rate is 15%.\n", None),
        ("problems", "- say where 15% comes from\n", None),
        ("revise", "15% (630 of 4,200).\n", None),
        ("ok", "", None)]
    assert mirror.body == "15% (630 of 4,200)."
    assert kinds(events).count("tool_call") == 4 and kinds(events).count("tool_result") == 4


def test_a_think_turn_counts_as_one_turn_for_numbering_and_the_next_think_turn_sees_it(web):
    page = think_page(web, ["Plan"], ["First answer"], ["Plan 2"], ["Second answer"],
                      checks=(Check(ok=True), Check(ok=True)))
    page.stream({"text": "one", "mode": "think"})
    _, events = page.stream({"text": "two", "mode": "think"})
    assert events[0]["number"] == 2
    assert page.client.calls[-2][1:3] == ["one", "First answer"]  # the second plan request starts from the saved pair
    items = page.call("GET", "/api/session")[1]["items"]
    assert [(i["kind"], i["text"]) for i in items] == [("user", "one"), ("assistant", "First answer"),
                                                       ("user", "two"), ("assistant", "Second answer")]


@pytest.mark.parametrize("mode", [None, "normal"])
def test_a_null_or_normal_mode_is_a_normal_turn(web, mode):
    page = think_page(web, ["plain"])
    _, events = page.stream({"text": "hi", "mode": mode})
    assert "think_section" not in kinds(events) and events[-1]["status"] == "completed"
    assert page.app.checker.calls == []


@pytest.mark.parametrize("mode", ["", "THINK", " think", True, 0])
def test_other_modes_are_refused_before_a_turn_starts(web, mode):
    page = think_page(web)
    status, payload = page.stream({"text": "hi", "mode": mode})
    assert (status, payload["error"]["code"]) == (400, "bad_request") and page.app.turn is None


# --- strings ------------------------------------------------------------------------------------------------


def test_think_strings_exist_in_both_languages_and_match_the_inventory():
    en = json.loads((STATIC / "js" / "strings.en.json").read_text(encoding="utf-8"))
    fr = json.loads((STATIC / "js" / "strings.fr.json").read_text(encoding="utf-8"))
    assert set(en) == set(fr)
    spec = SPEC.read_text(encoding="utf-8")
    assert f"## String keys ({len(en)} per language" in spec
    listed = re.search(r"^- `think` \((\d+)\): (.*)$", spec, re.M)
    names = re.findall(r"`([^`]+)`", listed.group(2))
    assert int(listed.group(1)) == len(names)
    assert sorted(f"think.{n}" for n in names) == sorted(k for k in en if k.startswith("think."))
    used = set()
    for name in ("chat/reasoning.js", "chat/turn.js", "views/chat.js"):
        used |= set(re.findall(r"t\('(think\.[\w.]+)'", (STATIC / "js" / name).read_text(encoding="utf-8")))
    for kind in ("plan", "act", "observe", "draft", "ok", "revise", "unresolved", "unavailable"):
        used.add(f"think.step.{kind}")
    for key in ("round", "tool", "problem", "unresolved"):
        used |= {f"think.{key}.one", f"think.{key}.other"}
    assert used <= set(en), used - set(en)
    assert all("—" not in en[k] and "—" not in fr[k] for k in en if k.startswith("think."))


def test_a_resumed_or_reloaded_session_holds_only_the_request_and_the_answer(web, tmp_path):
    page = think_page(web, ["Plan"], [CALC], ["The answer."])
    page.stream({"text": "rate?", "mode": "think"})
    session_id = page.call("GET", "/api/session")[1]["id"]
    assert page.call("POST", "/api/sessions")[0] == 200
    assert page.call("POST", f"/api/sessions/{session_id}/resume")[0] == 200
    pairs = [(i["kind"], i["text"], i.get("tools")) for i in page.call("GET", "/api/session")[1]["items"]]
    assert pairs == [("user", "rate?", None), ("assistant", "The answer.", [])]
    listed = next(s for s in page.call("GET", "/api/sessions")[1]["items"] if s["id"] == session_id)
    assert listed["messages"] == 2
    restarted = web(["after"], session=session_id)
    items = restarted.call("GET", "/api/session")[1]["items"]
    assert [(i["kind"], i["text"]) for i in items] == [("user", "rate?"), ("assistant", "The answer.")]
