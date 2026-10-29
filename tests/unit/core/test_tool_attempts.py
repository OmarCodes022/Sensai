"""T21 registry: attempt counts, the attempt prefix and the stop message."""

import json

import pytest

from fakes import FakeClient
from sensai.chat.session import ChatSession
from sensai.core.ports import ApprovalDecision, ToolDefinition, ToolResult
from sensai.tools import ToolRegistry, run_with_tools

LAST = "\nThis was the last attempt: answer with this result or error, without calling probe again."
STOP = "Stopped after 2 attempts: answer with the last result or error, without calling probe again."


def handler(arguments, cancellation=None):
    return ToolResult("", "boom") if arguments.get("fail") else ToolResult("ok")


class Approval:
    def __init__(self, *answers):
        self.answers = list(answers)

    def request(self, request):
        return ApprovalDecision(self.answers.pop(0))


def tools(approval=None, **settings):
    registry = ToolRegistry(approval)
    registry.register(ToolDefinition("probe", "Probe"), handler, timeout=None, **settings)
    return registry


def call(**arguments):
    return [json.dumps({"tool": "probe", "arguments": arguments})]


def ask(registry, *replies):
    client = FakeClient(*replies)
    seen = []
    stream = run_with_tools(ChatSession(client, "m", "sys"), registry, "Q",
                            on_tool=lambda c, result: seen.append(result))
    for _ in stream:
        pass
    return [m.content for _, messages in client.requests[1:] for m in messages[-1:]], seen


def test_usage_counts_calls_and_resets_per_question():
    registry = tools(max_calls=3)
    assert registry.usage("probe") == (0, 3)
    assert registry.usage("missing") == (0, None) and registry.usage(None) == (0, None)
    ask(registry, call(), call(), ["done"])
    assert registry.usage("probe") == (2, 3)
    ask(registry, ["no tool"])
    assert registry.usage("probe") == (0, 3)
    assert tools().usage("probe") == (0, None)


def test_results_errors_and_refusals_carry_the_attempt_prefix():
    registry = tools(Approval(True, True, False), confirm=True, max_calls=3)
    sent, seen = ask(registry, call(), call(fail=True), call(), ["done"])
    assert sent == ["Tool result from probe:\nAttempt 1 of 3 · ok",
                    "Tool error from probe:\nAttempt 2 of 3 · boom",
                    "Tool error from probe:\nAttempt 3 of 3 · tool approval refused" + LAST]
    # The observer gets the handler's own result, without the prefix.
    assert seen == [ToolResult("ok"), ToolResult("", "boom"), ToolResult("", "tool approval refused")]


def test_call_past_the_limit_gets_the_exact_stop_message_without_prefix():
    registry = tools(max_calls=2)
    sent, seen = ask(registry, call(), call(), call(), ["done"])
    assert sent[2] == f"Tool error from probe:\n{STOP}"
    assert seen[2] == ToolResult("", STOP)


def test_zero_max_calls_keeps_the_old_message_and_no_prefix():
    sent, _ = ask(tools(max_calls=0), call(), ["done"])
    assert sent == ["Tool error from probe:\ntool call limit reached"]


@pytest.mark.parametrize("settings", [{}, {"max_calls": None}])
def test_tools_without_max_calls_get_no_prefix(settings):
    sent, _ = ask(tools(**settings), call(), call(fail=True), ["done"])
    assert sent == ["Tool result from probe:\nok", "Tool error from probe:\nboom"]


def test_malformed_block_gets_no_prefix():
    sent, _ = ask(tools(max_calls=3), ['{"tool": ""}'], ["done"])
    assert sent == ["Tool error from <invalid>:\ntool must be a nonblank string"]


def test_last_attempt_line_comes_before_the_round_note():
    client = FakeClient(call(), call(), ["done"])
    stream = run_with_tools(ChatSession(client, "m", "sys"), tools(max_calls=2), "Q", max_rounds=2)
    for _ in stream:
        pass
    first, second = [request[-1].content for _, request in client.requests[1:]]
    assert first == "Tool result from probe:\nAttempt 1 of 2 · ok"
    assert second == ("Tool result from probe:\nAttempt 2 of 2 · ok" + LAST
                      + "\nTool round limit reached. Give a final answer without tools.")
