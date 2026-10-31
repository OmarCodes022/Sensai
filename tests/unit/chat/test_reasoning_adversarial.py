"""Adversarial checks of the /think loop: exact budget, stages that stop, what the check sees."""

import random

import pytest

from fakes import FakeClient
from sensai.chat import reasoning
from sensai.chat.reasoning import NO_TOOLS, Budget, Check, Section, think
from sensai.chat.session import ChatSession
from sensai.core.cancellation import CancellationToken, OperationCancelled, OperationTimedOut
from sensai.core.errors import LLMError
from sensai.core.ports import ToolDefinition, ToolResult
from sensai.llm.structured import StructuredOutputError
from sensai.tools import ToolRegistry, tool_instructions

LOOKUP = '{"tool":"lookup","arguments":{}}'


class Checker:
    """Replays Check objects (the last one repeats) or raises; records each request."""

    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def complete(self, model, messages, schema):
        assert schema is Check
        self.calls.append(list(messages))
        result = self.results.pop(0) if len(self.results) > 1 else self.results[0]
        if isinstance(result, BaseException):
            raise result
        return result


class EndlessClient(FakeClient):
    """Replies forever with ``reply(n)`` for the n-th request (0 = plan)."""

    def __init__(self, reply):
        super().__init__()
        self.reply = reply

    def stream(self, model, messages, cancellation=None):
        self.replies = [self.reply(len(self.requests))]
        return super().stream(model, messages, cancellation)


def tools_with(handler=None):
    tools = ToolRegistry()
    tools.register(ToolDefinition("lookup", "Look up."),
                   handler or (lambda arguments, cancellation: ToolResult("7")), timeout=None)
    return tools


def session_for(client, tools, prompt="Rules: approved claims only."):
    return ChatSession(client, "model", f"{prompt}\n\n{tool_instructions(tools.definitions())}")


def drive(stream, on_item=lambda item: None):
    items = []
    while True:
        try:
            item = next(stream)
        except StopIteration as stop:
            return items, stop.value
        items.append(item)
        on_item(item)


def run(session, tools, checker, request="Summarize", new_token=CancellationToken, **kwargs):
    return drive(think(session, tools, request, checker, new_token=new_token, **kwargs))


def titles(items):
    return [item.title for item in items if isinstance(item, Section)]


# --- Budget -------------------------------------------------------------------------------

def test_a_model_that_always_calls_tools_gets_exactly_eight_replies():
    tools = tools_with()
    client = EndlessClient(lambda n: ["Plan"] if n == 0 else ["Working\n", LOOKUP])
    checker = Checker(Check(ok=False, problems=["x"]))
    items, result = run(session_for(client, tools), tools, checker)
    assert len(client.requests) == 8 and len(checker.calls) == 1
    assert result.tool_calls == 6 and result.unresolved == ("x",)


def test_a_check_that_always_fails_gets_exactly_three_checks():
    tools = tools_with()
    client = EndlessClient(lambda n: [f"D{n}"])
    checker = Checker(Check(ok=False, problems=["x"]))
    items, result = run(session_for(client, tools), tools, checker)
    assert len(checker.calls) == 3 and len(client.requests) == 4
    assert titles(items).count("Revise") == 2 and result.answer == "D3"


@pytest.mark.parametrize("seed", range(60))
def test_random_scripts_never_exceed_the_budget(seed):
    rng = random.Random(seed)
    tools = tools_with()
    client = EndlessClient(lambda n: rng.choice([["Text"], ["Text\n", LOOKUP], [LOOKUP]])
                           if n else ["Plan"])
    checker = Checker(*[rng.choice([Check(ok=True), Check(ok=False, problems=["p"])])
                        for _ in range(4)])
    try:
        items, result = run(session_for(client, tools), tools, checker)
    except LLMError:  # A last reply that is only a hidden tool block (accepted ruling).
        assert len(client.requests) <= 8 and len(checker.calls) <= 3
        return
    assert len(client.requests) <= 8 and len(checker.calls) <= 3
    if result.unresolved:  # Problems remain only once a budget is used up.
        assert len(client.requests) == 8 or len(checker.calls) == 3
    assert result.tool_calls == titles(items).count("Act")


def test_max_rounds_is_always_the_steps_left_minus_one(monkeypatch):
    seen = []
    real = reasoning.run_with_tools

    def spy(session, registry, text, token, *, max_rounds, on_tool, new_question):
        seen.append((len(client.requests), max_rounds))
        return real(session, registry, text, token, max_rounds=max_rounds, on_tool=on_tool,
                    new_question=new_question)

    monkeypatch.setattr(reasoning, "run_with_tools", spy)
    tools = tools_with()
    # plan, 2 tool rounds + draft, 1 tool round + revise, then 1 step left: no tools.
    script = [["Plan"], [LOOKUP], [LOOKUP], ["D1"], [LOOKUP], ["D2"], ["D3"]]
    client = FakeClient(*script)
    checker = Checker(Check(ok=False, problems=["x"]), Check(ok=False, problems=["y"]),
                      Check(ok=False, problems=["z"]))
    _, result = run(session_for(client, tools), tools, checker, budget=Budget(steps=7))
    assert seen == [(1, 5), (4, 2)]
    assert client.calls[-1][-1].endswith(NO_TOOLS)
    assert len(client.requests) == 7 and result.unresolved == ("z",)


@pytest.mark.parametrize("steps", [2, 3])
def test_a_tiny_budget_never_runs_more_tools_than_it_can_pay_for(steps):
    calls = []
    tools = tools_with(lambda arguments, cancellation: calls.append(1) or ToolResult("7"))
    client = EndlessClient(lambda n: ["Plan"] if n == 0 else ["Text\n", LOOKUP])
    _, result = run(session_for(client, tools), tools, Checker(Check(ok=True)),
                    budget=Budget(steps=steps))
    assert len(client.requests) == steps
    assert len(calls) == result.tool_calls == steps - 2
    assert result.answer == "Text"


def test_budget_rejects_bools_and_floats():
    for bad in ({"steps": True}, {"steps": 8.0}, {"checks": True}, {"checks": 3.0}):
        with pytest.raises(ValueError):
            Budget(**bad)


# --- Stages that stop: the real session is never touched ----------------------------------

class Flag:
    def __init__(self):
        self.on = False

    def __call__(self):
        return self.on


def stopped(stage, error):
    """Run /think with a cancel request (or deadline) raised at ``stage``; return the outcome."""
    flag = Flag()
    tools = tools_with(lambda arguments, cancellation: (
        (setattr(flag, "on", True) if stage == "tool" else None), ToolResult("7"))[1])
    client = FakeClient(["Plan"], [LOOKUP], ["D1"], ["half", OperationCancelled("stop")]
                        if stage == "revise" else ["D2"])
    session = session_for(client, tools)
    before = list(session.messages)
    checker = Checker(Check(ok=False, problems=["x"]), Check(ok=True))
    seen = []

    def on_item(item):
        seen.append(item)
        if stage == "before check" and item == Section("Draft"):
            flag.on = True
        if stage == "plan" and item == Section("Plan"):
            flag.on = True

    def new_token():
        deadline = 0.0 if error is OperationTimedOut and flag.on else None
        return CancellationToken(deadline, flag if error is OperationCancelled else None)

    with pytest.raises(error):
        drive(think(session, tools, "Q", checker, new_token=new_token), on_item)
    assert session.messages == before
    return client, checker, seen


@pytest.mark.parametrize("stage", ["plan", "tool", "before check", "revise"])
def test_cancel_at_any_stage_propagates_and_leaves_the_session(stage):
    client, checker, seen = stopped(stage, OperationCancelled)
    if stage == "before check":
        assert checker.calls == []  # The token is checked before the check request.
    if stage == "revise":
        assert len(checker.calls) == 1 and Section("Revise") not in seen


def test_deadline_of_the_check_step_stops_before_the_request():
    client, checker, _ = stopped("before check", OperationTimedOut)
    assert checker.calls == []


@pytest.mark.parametrize("error", [KeyboardInterrupt(), OperationTimedOut("late"),
                                   LLMError("down")])
def test_failures_during_the_revise_check_leave_the_session(error):
    tools = tools_with()
    client = FakeClient(["Plan"], ["D1"], ["D2"])
    session = session_for(client, tools)
    before = list(session.messages)
    with pytest.raises(type(error)):
        run(session, tools, Checker(Check(ok=False, problems=["x"]), error))
    assert session.messages == before


def test_structured_error_after_a_revise_keeps_the_revised_draft_unchecked():
    tools = tools_with()
    client = FakeClient(["Plan"], ["D1"], ["D2"])
    checker = Checker(Check(ok=False, problems=["x"]), StructuredOutputError("bad"))
    items, result = run(session_for(client, tools), tools, checker)
    assert titles(items)[-2:] == ["Check unavailable", "Final answer (2 rounds, 0 tool calls)"]
    assert (result.answer, result.checked, result.unresolved) == ("D2", False, ())
    assert "Check — ok" not in titles(items)


# --- What the check sees -------------------------------------------------------------------

def test_every_check_gets_the_request_plan_all_results_and_its_own_draft():
    outputs = iter(["first\nline2", "x" * 700])
    tools = tools_with(lambda arguments, cancellation: ToolResult(next(outputs)))
    client = FakeClient(["1. Look up"], [LOOKUP], ["D1"], [LOOKUP], ["D2"])
    checker = Checker(Check(ok=False, problems=["x"]), Check(ok=True))
    run(session_for(client, tools), tools, checker, request="Weekly {summary}")
    first, second = (messages[1].content for messages in checker.calls)
    assert first.startswith("Request:\nWeekly {summary}\n\nPlan:\n1. Look up\n")
    assert "- lookup({}): first\nline2" in first and first.endswith("Draft:\nD1")
    # The second check also sees the earlier result and the full, uncut new result.
    assert "- lookup({}): first\nline2" in second and "x" * 700 in second
    assert second.endswith("Draft:\nD2")
    for messages in checker.calls:
        assert [m.role for m in messages] == ["system", "user"]
        assert messages[0].content.endswith("Rules:\nRules: approved claims only.")


def test_a_tool_error_reaches_the_check_and_the_observation():
    tools = tools_with(lambda arguments, cancellation: ToolResult("", "sheet missing"))
    client = FakeClient(["Plan"], [LOOKUP], ["No data."])
    checker = Checker(Check(ok=True))
    items, _ = run(session_for(client, tools), tools, checker)
    assert items[items.index(Section("Observe")) + 1] == "sheet missing\n"
    assert "- lookup({}): sheet missing" in checker.calls[0][1].content


# --- Display of a tool round ---------------------------------------------------------------

def test_act_and_observe_are_emitted_before_the_next_model_reply_starts():
    tools = tools_with()
    client = FakeClient(["Plan"], ["Looking.\n", LOOKUP], ["Done."])
    emitted, requests_at_observe = [], []

    def emit(item):
        emitted.append(item)
        if item == Section("Observe"):
            requests_at_observe.append(len(client.requests))

    items, _ = drive(think(session_for(client, tools), tools, "Q", Checker(Check(ok=True)),
                           new_token=CancellationToken, emit=emit))
    assert requests_at_observe == [2]  # plan + the tool round, not yet the draft
    assert emitted == ["Looking.\n", Section("Act"), "lookup({})\n", Section("Observe"), "7\n"]
    assert not set(emitted[1:]) & set(items)  # Emitted items are not yielded again.


def test_a_completed_round_is_shown_even_if_the_next_reply_fails():
    tools = tools_with()
    client = FakeClient(["Plan"], [LOOKUP], OperationCancelled("Esc"))
    seen = []
    with pytest.raises(OperationCancelled):
        drive(think(session_for(client, tools), tools, "Q", Checker(Check(ok=True)),
                    new_token=CancellationToken, emit=seen.append), seen.append)
    assert Section("Act") in seen and Section("Observe") in seen


def test_two_rounds_keep_pre_tool_text_in_order():
    tools = tools_with()
    client = FakeClient(["Plan"], ["First.\n", LOOKUP], ["Second.\n", LOOKUP], ["Done."])
    items, result = run(session_for(client, tools), tools, Checker(Check(ok=True)))
    text = "".join(f"[{i.title}]\n" if isinstance(i, Section) else i for i in items)
    assert ("Plan\nFirst.\n[Act]\nlookup({})\n[Observe]\n7\n"
            "Second.\n[Act]\nlookup({})\n[Observe]\n7\n[Draft]\nDone.\n") in text
    assert result.tool_calls == 2


def test_control_characters_in_a_round_are_left_for_the_cli_to_escape():
    tools = ToolRegistry()
    tools.register(ToolDefinition("lookup", "Look up."),
                   lambda arguments, cancellation: ToolResult("a\x1bb\rc"), timeout=None)
    block = '{"tool":"lookup","arguments":{"q":"x\\u001by\\ud800"}}'
    client = FakeClient(["Plan"], [block], ["Done."])
    items, _ = run(session_for(client, tools), tools, Checker(Check(ok=True)))
    # JSON escapes the control character; a lone surrogate stays raw for the CLI to escape.
    assert items[items.index(Section("Act")) + 1] == 'lookup({"q":"x\\u001by\ud800"})\n'
    assert items[items.index(Section("Observe")) + 1] == "a\x1bb\nc\n"  # splitlines() on \r


def test_scratch_never_aliases_the_real_message_list():
    tools = tools_with()
    client = FakeClient(["Plan"], ["Done."])
    session = session_for(client, tools)
    ids = id(session.messages)
    run(session, tools, Checker(Check(ok=True)))
    assert id(session.messages) == ids and len(session.messages) == 1
    assert session.system_prompt_changed is False


def test_a_tool_block_in_the_plan_is_hidden_and_never_run():
    calls = []
    tools = tools_with(lambda arguments, cancellation: calls.append(1) or ToolResult("7"))
    client = FakeClient(["1. Look up\n", LOOKUP], ["Done."])
    checker = Checker(Check(ok=True))
    items, result = run(session_for(client, tools), tools, checker)
    assert calls == [] and result.tool_calls == 0 and len(client.requests) == 2
    assert items[:3] == [Section("Plan"), "1. Look up\n", Section("Draft")]
    assert "Plan:\n1. Look up\n\n" in checker.calls[0][1].content
