"""The /think loop on a scratch session: sections, budget, checks and failures."""

import pytest

from fakes import FakeClient
from sensai.chat.reasoning import NO_TOOLS, Budget, Check, Section, think
from sensai.chat.session import ChatSession
from sensai.core.cancellation import CancellationToken, OperationCancelled
from sensai.core.errors import LLMError
from sensai.core.ports import ToolDefinition, ToolResult
from sensai.llm.structured import StructuredOutputError
from sensai.tools import CALCULATE, ToolRegistry, calculate, tool_instructions

RATE = '{"tool":"calculate","arguments":{"expression":"630 / 4200 * 100"}}'
LOOKUP = '{"tool":"lookup","arguments":{}}'
PROBLEM = '"cures eczema" is not an approved claim'


class FakeChecker:
    """Replays Check objects or raises exceptions; records each request."""

    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def complete(self, model, messages, schema):
        assert schema is Check
        self.calls.append((model, list(messages)))
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


def registry(output="7", error=None):
    tools = ToolRegistry()
    tools.register(CALCULATE, calculate, timeout=None)

    def lookup(arguments, cancellation):
        if isinstance(error, BaseException):
            raise error
        return ToolResult(output, error)

    tools.register(ToolDefinition("lookup", "Look up."), lookup, timeout=None)
    return tools


def session_for(client, tools, prompt="Rules: approved claims only."):
    return ChatSession(client, "model", f"{prompt}\n\n{tool_instructions(tools.definitions())}")


def run(session, tools, checker, request="Summarize", **kwargs):
    tokens = []

    def new_token():
        tokens.append(CancellationToken())
        return tokens[-1]

    items = []
    stream = think(session, tools, request, checker, new_token=new_token, **kwargs)
    while True:
        try:
            items.append(next(stream))
        except StopIteration as stop:
            return items, stop.value, tokens


def titles(items):
    return [item.title for item in items if isinstance(item, Section)]


def text(items):
    return "".join(f"[{item.title}]\n" if isinstance(item, Section) else item for item in items)


def test_tool_call_figure_problem_revise_ok_in_order_and_check_sees_everything():
    tools = registry()
    client = FakeClient(["1. Compute the rate\n", "2. Write"], ["Computing.\n", RATE],
                        ["15% engaged. Cures eczema!"], ["15% engaged. Hydrates."])
    session = session_for(client, tools)
    checker = FakeChecker(Check(ok=False, problems=[PROBLEM]), Check(ok=True))
    items, result, tokens = run(session, tools, checker)
    assert text(items) == (
        "[Plan]\n1. Compute the rate\n2. Write\nComputing.\n"
        '[Act]\ncalculate({"expression":"630 / 4200 * 100"})\n[Observe]\n15.0\n'
        "[Draft]\n15% engaged. Cures eczema!\n"
        f"[Check — 1 problem]\n- {PROBLEM}\n"
        "[Revise]\n15% engaged. Hydrates.\n[Check — ok]\n"
        "[Final answer (2 rounds, 1 tool call)]\n15% engaged. Hydrates.\n")
    assert result.answer == "15% engaged. Hydrates."
    assert (result.rounds, result.tool_calls, result.unresolved, result.checked) == (2, 1, (), True)
    model, (system, user) = checker.calls[0]
    assert model == "model" and system.role == "system" and user.role == "user"
    assert "Rules: approved claims only." in system.content
    assert "Available tools" not in system.content
    assert "Summarize" in user.content and "1. Compute the rate" in user.content
    assert '- calculate({"expression":"630 / 4200 * 100"}): 15.0' in user.content
    assert user.content.endswith("15% engaged. Cures eczema!")
    assert PROBLEM in client.calls[-1][-1]  # The revise prompt lists the problems.
    assert len(tokens) == 5  # plan, draft, check, revise, check: one deadline each.


def test_no_tool_request_has_plan_draft_check_and_final_answer_only():
    tools = registry()
    client = FakeClient(["1. Write it"], ["Hello!"])
    items, result, _ = run(session_for(client, tools), tools, FakeChecker(Check(ok=True)))
    assert titles(items) == ["Plan", "Draft", "Check — ok", "Final answer (1 round, 0 tool calls)"]
    assert result.answer == "Hello!" and result.tool_calls == 0


def test_number_that_differs_from_the_tool_result_is_flagged():
    class NumberChecker(FakeChecker):
        def complete(self, model, messages, schema):
            self.calls.append(messages)
            check_input = messages[-1].content
            if "): 15.0" in check_input and "16%" in check_input.split("Draft:")[1]:
                return Check(ok=False, problems=["16% differs from the tool result 15.0"])
            return Check(ok=True)

    tools = registry()
    client = FakeClient(["1. Compute"], [RATE], ["16% engaged."], ["15% engaged."])
    checker = NumberChecker()
    items, result, _ = run(session_for(client, tools), tools, checker)
    assert titles(items)[4:7] == ["Check — 1 problem", "Revise", "Check — ok"]
    assert "- 16% differs from the tool result 15.0\n" in items
    assert result.answer == "15% engaged."


def test_checks_exhausted_list_unresolved_problems_with_last_draft():
    tools = registry()
    client = FakeClient(["Plan"], ["D1"], ["D2"], ["D3"])
    checker = FakeChecker(*[Check(ok=False, problems=["a", "b"])] * 3)
    items, result, _ = run(session_for(client, tools), tools, checker)
    assert titles(items) == ["Plan", "Draft", "Check — 2 problems", "Revise", "Check — 2 problems",
                             "Revise", "Check — 2 problems", "Unresolved",
                             "Final answer (3 rounds, 0 tool calls)"]
    assert text(items).endswith("[Unresolved]\n- a\n- b\n[Final answer (3 rounds, 0 tool calls)]\nD3\n")
    assert (result.answer, result.unresolved, result.checked) == ("D3", ("a", "b"), True)
    assert len(checker.calls) == 3 and len(client.requests) == 4


def test_tool_rounds_use_the_whole_step_budget_in_one_act_step():
    tools = registry()
    client = FakeClient(["Plan"], *[[LOOKUP]] * 6, ["Answer\n", LOOKUP])
    checker = FakeChecker(Check(ok=False, problems=["x"]), Check(ok=True))
    items, result, _ = run(session_for(client, tools), tools, checker)
    assert len(client.requests) == 8  # plan + 6 tool rounds + the forced final reply
    assert len(checker.calls) == 1
    assert result.tool_calls == 6 and result.unresolved == ("x",) and result.answer == "Answer"
    assert titles(items)[-2:] == ["Unresolved", "Final answer (1 round, 6 tool calls)"]


@pytest.mark.parametrize("last, answer", [([LOOKUP], None), (['{"answer": 15}'], '{"answer": 15}')])
def test_a_final_reply_with_only_a_block(last, answer):
    tools = registry()
    client = FakeClient(["Plan"], *[[LOOKUP]] * 6, last)
    session = session_for(client, tools)
    if answer is None:  # A hidden tool block leaves no answer to show or keep.
        with pytest.raises(LLMError, match="no visible answer"):
            run(session, tools, FakeChecker(Check(ok=True)))
    else:
        assert run(session, tools, FakeChecker(Check(ok=True)))[1].answer == answer


def test_act_is_skipped_when_fewer_than_two_steps_are_left():
    tools = registry()
    client = FakeClient(["Plan"], *[[LOOKUP]] * 5, ["D1"], ["D2\n", LOOKUP])
    checker = FakeChecker(Check(ok=False, problems=["x"]), Check(ok=False, problems=["y"]))
    items, result, _ = run(session_for(client, tools), tools, checker)
    assert len(client.requests) == 8
    assert client.calls[-1][-1].endswith(NO_TOOLS)
    assert result.tool_calls == 5  # The tool block of the last reply is hidden, not executed.
    assert result.answer == "D2" and result.unresolved == ("y",)
    assert titles(items).count("Act") == 5


def test_custom_budget_is_respected_and_validated():
    tools = registry()
    client = FakeClient(["Plan"], ["D1"])
    checker = FakeChecker(Check(ok=False, problems=["x"]))
    _, result, _ = run(session_for(client, tools), tools, checker, budget=Budget(steps=2, checks=1))
    assert len(client.requests) == 2 and result.unresolved == ("x",)
    with pytest.raises(ValueError):
        Budget(steps=1)
    with pytest.raises(ValueError):
        Budget(checks=0)


def test_tool_error_is_the_observation_and_the_loop_continues():
    tools = registry(error=RuntimeError("sheet missing"))
    client = FakeClient(["Plan"], [LOOKUP], ["No data."])
    items, result, _ = run(session_for(client, tools), tools, FakeChecker(Check(ok=True)))
    assert "[Observe]\nRuntimeError: sheet missing\n[Draft]\nNo data.\n" in text(items)
    assert result.answer == "No data." and result.tool_calls == 1


@pytest.mark.parametrize("output, shown", [
    ("\n".join(map(str, range(10))), "0\n1\n2\n3\n4\n5 …\n"),
    ("x" * 600, "x" * 500 + " …\n"),
    ("short", "short\n"),
])
def test_observation_is_cut_to_six_lines_and_500_characters(output, shown):
    tools = registry(output=output)
    client = FakeClient(["Plan"], [LOOKUP], ["Done."])
    items, _, _ = run(session_for(client, tools), tools, FakeChecker(Check(ok=True)))
    assert items[items.index(Section("Observe")) + 1] == shown


def test_failed_check_is_shown_as_unavailable_with_the_last_draft():
    tools = registry()
    client = FakeClient(["Plan"], ["Draft text"])
    checker = FakeChecker(StructuredOutputError("invalid JSON content from Ollama"))
    items, result, _ = run(session_for(client, tools), tools, checker)
    assert titles(items) == ["Plan", "Draft", "Check unavailable", "Final answer (1 round, 0 tool calls)"]
    assert (result.answer, result.checked) == ("Draft text", False)


def test_ok_with_problems_or_not_ok_without_problems_is_not_a_pass():
    tools = registry()
    client = FakeClient(["Plan"], ["D1"], ["D2"], ["D3"])
    checker = FakeChecker(Check(ok=True, problems=["x"]), Check(ok=False), Check(ok=True, problems=[" "]))
    items, result, _ = run(session_for(client, tools), tools, checker)
    assert titles(items)[-2] == "Check — ok"
    assert result.answer == "D3" and result.rounds == 3


@pytest.mark.parametrize("failure", [
    "plan", "tool", "check", "llm", "draft",
])
def test_errors_propagate_and_the_real_session_is_untouched(failure):
    tools = registry(error=KeyboardInterrupt() if failure == "tool" else None)
    replies = {"plan": [["1.", OperationCancelled("stop")]],
               "draft": [["Plan"], ["half", OperationCancelled("stop")]]}
    client = FakeClient(*replies.get(failure, [["Plan"], [LOOKUP], ["Done."]]))
    session = session_for(client, tools)
    before = list(session.messages)
    error = {"check": OperationCancelled("stop"), "llm": LLMError("down")}.get(failure, Check(ok=True))
    expected = {"tool": KeyboardInterrupt, "llm": LLMError}.get(failure, OperationCancelled)
    with pytest.raises(expected):
        run(session, tools, FakeChecker(error))
    assert session.messages == before


def test_success_never_modifies_the_real_session():
    tools = registry()
    client = FakeClient(["Plan"], [LOOKUP], ["Done."])
    session = session_for(client, tools)
    before = list(session.messages)
    run(session, tools, FakeChecker(Check(ok=True)))
    assert session.messages == before


def test_cancel_requested_during_the_check_stops_after_it_returns():
    tools = registry()
    client = FakeClient(["Plan"], ["Draft"])
    requested = []
    checker = FakeChecker(Check(ok=True))
    original = checker.complete
    checker.complete = lambda *args: requested.append(True) or original(*args)
    stream = think(session_for(client, tools), tools, "Q", checker,
                   new_token=lambda: CancellationToken(None, lambda: bool(requested)))
    with pytest.raises(OperationCancelled):
        list(stream)
    assert len(checker.calls) == 1


def test_scratch_keeps_the_conversation_and_the_switched_system_prompt():
    tools = registry()
    client = FakeClient(["A1"], ["Plan"], ["Done."])
    session = session_for(client, tools)
    list(session.send("Q1"))
    session.set_system_prompt("Persona rules")
    checker = FakeChecker(Check(ok=True))
    run(session, tools, checker, request="Write a caption")
    plan_request = client.calls[1]
    assert plan_request[:3] == ["Persona rules", "Q1", "A1"]
    assert plan_request[3] == "Persona rules"  # Re-sent before the request, as in send().
    assert "Write a caption" in plan_request[4] and "calculate, lookup" in plan_request[4]
    assert checker.calls[0][1][0].content.endswith("Rules:\nPersona rules")


def test_on_tool_observer_sees_every_round():
    tools = registry()
    client = FakeClient(["Plan"], [LOOKUP], ["Done."])
    seen = []
    run(session_for(client, tools), tools, FakeChecker(Check(ok=True)),
        on_tool=lambda call, result: seen.append((call.name, result.output)))
    assert seen == [("lookup", "7")]
