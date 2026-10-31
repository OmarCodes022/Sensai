"""T21 registry edge cases: attempt numbering over a whole question, the round limit, rollback."""

import json

import pytest

from fakes import FakeClient
from sensai.chat import saved_sessions
from sensai.chat.session import ChatSession
from sensai.core.ports import ApprovalDecision, ToolDefinition, ToolResult
from sensai.tools import CALCULATE, ToolRegistry, calculate, run_with_tools

PROBE = ToolDefinition("probe", "Probe", {"type": "object", "properties": {"n": {"type": "integer"}},
                                          "required": ["n"], "additionalProperties": False})
ROUND_NOTE = "\nTool round limit reached. Give a final answer without tools."


def last(name="probe"):
    return f"\nThis was the last attempt: answer with this result or error, without calling {name} again."


def stop(limit, name="probe"):
    return (f"Stopped after {limit} attempts: answer with the last result or error, "
            f"without calling {name} again.")


class Handler:
    def __init__(self):
        self.calls = []

    def __call__(self, arguments, cancellation=None):
        self.calls.append(arguments["n"])
        return ToolResult(f"ran {arguments['n']}") if arguments["n"] % 2 else ToolResult("", "boom")


class Approval:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.asked = 0

    def request(self, request):
        self.asked += 1
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return ApprovalDecision(answer)


def tools(approval=None, max_calls=3, handler=None, **settings):
    registry = ToolRegistry(approval)
    handler = handler or Handler()
    registry.register(PROBE, handler, timeout=None, max_calls=max_calls, **settings)
    registry.register(CALCULATE, calculate, timeout=None)
    return registry, handler


def call(n=None, tool="probe", **arguments):
    if n is not None:
        arguments["n"] = n
    return [json.dumps({"tool": tool, "arguments": arguments})]


def ask(registry, *replies, session=None, text="Q", **options):
    client = FakeClient(*replies)
    session = session or ChatSession(client, "m", "sys")
    session.client = client
    seen = []
    stream = run_with_tools(session, registry, text, on_tool=lambda c, r: seen.append((c.name, r)),
                            **options)
    visible = "".join(stream)
    return [request[-1].content for _, request in client.requests[1:]], seen, visible, session


def test_five_rounds_number_three_attempts_then_stop_twice_with_the_round_note_last():
    approval = Approval(True, True, True)
    registry, handler = tools(approval, confirm=True)
    sent, seen, visible, _ = ask(registry, *[call(n) for n in range(1, 6)],
                                 ["Answer\n"] + call(6))
    assert handler.calls == [1, 2, 3] and approval.asked == 3
    assert sent == [
        "Tool result from probe:\nAttempt 1 of 3 · ran 1",
        "Tool error from probe:\nAttempt 2 of 3 · boom",
        f"Tool result from probe:\nAttempt 3 of 3 · ran 3{last()}",
        f"Tool error from probe:\n{stop(3)}",
        f"Tool error from probe:\n{stop(3)}{ROUND_NOTE}",
    ]
    # The last reply's tool block is hidden and not executed.
    assert visible.strip() == "Answer" and handler.calls == [1, 2, 3]
    assert [r for _, r in seen][3:] == [ToolResult("", stop(3))] * 2
    assert registry.usage("probe") == (5, 3)


def test_round_note_follows_a_prefixed_result_when_the_limit_is_reached_within_attempts():
    registry, _ = tools()
    sent, *_ = ask(registry, call(1), call(2), ["done"], max_rounds=2)
    assert sent == ["Tool result from probe:\nAttempt 1 of 3 · ran 1",
                    f"Tool error from probe:\nAttempt 2 of 3 · boom{ROUND_NOTE}"]


def test_numbering_restarts_on_the_next_question_after_running_out():
    registry, handler = tools()
    session = None
    _, _, _, session = ask(registry, *[call(n) for n in (1, 3, 5, 7)], ["gave up"])
    sent, *_ = ask(registry, call(9), ["ok"], session=session, text="Q2")
    assert sent[-1] == "Tool result from probe:\nAttempt 1 of 3 · ran 9"
    assert handler.calls == [1, 3, 5, 9]


def test_invalid_arguments_and_refusals_count_as_attempts():
    approval = Approval(False, True)
    registry, handler = tools(approval, confirm=True)
    sent, *_ = ask(registry, call(), call(tool="probe", n="x"), call(1), call(3), call(5), ["done"])
    assert sent[0] == "Tool error from probe:\nAttempt 1 of 3 · invalid arguments: missing required property n"
    assert sent[1] == "Tool error from probe:\nAttempt 2 of 3 · invalid arguments: n must be integer"
    assert sent[2] == f"Tool error from probe:\nAttempt 3 of 3 · tool approval refused{last()}"
    # Past the limit: no approval is asked and the handler never runs.
    assert sent[3] == f"Tool error from probe:\n{stop(3)}"
    assert approval.asked == 1 and handler.calls == []


def test_stopped_calls_are_not_validated_nor_approved():
    approval = Approval(True)
    registry, handler = tools(approval, max_calls=1, confirm=True)
    sent, *_ = ask(registry, call(1), call(), ["done"])
    assert sent[0] == f"Tool result from probe:\nAttempt 1 of 1 · ran 1{last()}"
    assert sent[1].startswith("Tool error from probe:\nStopped after 1 attempt")
    assert "invalid arguments" not in sent[1] and approval.asked == 1


def test_limit_of_one_says_one_attempt():
    registry, _ = tools(max_calls=1)
    sent, *_ = ask(registry, call(1), call(1), ["done"])
    assert sent[1] == ("Tool error from probe:\nStopped after 1 attempt: answer with the last "
                       "result or error, without calling probe again.")


def test_other_tools_malformed_blocks_and_unknown_tools_do_not_use_attempts():
    registry, _ = tools()
    sent, *_ = ask(registry, call(1), call(tool="calculate", expression="1+1"), ['{"tool": 3}'],
                   call(tool="nope"), call(3), ["done"])
    assert sent == [
        "Tool result from probe:\nAttempt 1 of 3 · ran 1",
        "Tool result from calculate:\n2",
        "Tool error from <invalid>:\ntool must be a nonblank string",
        "Tool error from nope:\nunknown tool",
        f"Tool result from probe:\nAttempt 2 of 3 · ran 3{ROUND_NOTE}",
    ]


def test_handler_exception_is_prefixed_like_any_error():
    def broken(arguments, cancellation=None):
        raise RuntimeError("kaput")

    registry, _ = tools(handler=broken)
    sent, seen, *_ = ask(registry, call(1), ["done"])
    assert sent == ["Tool error from probe:\nAttempt 1 of 3 · RuntimeError: kaput"]
    assert seen == [("probe", ToolResult("", "RuntimeError: kaput"))]


def test_prefixed_protocol_messages_stay_hidden_from_user_messages():
    registry, _ = tools()
    *_, session = ask(registry, call(1), call(2), call(3), call(5), ["done"], text="Question")
    contents = [m.content for m in session.messages]
    assert sum("Attempt" in c for c in contents) == 3 and any("Stopped after" in c for c in contents)
    assert saved_sessions.user_messages(session.messages) == ["Question"]


def test_interrupt_at_the_second_approval_rolls_back_and_the_next_question_starts_at_one():
    approval = Approval(True, KeyboardInterrupt(), True)
    registry, handler = tools(approval, confirm=True)
    client = FakeClient(call(1), call(3))
    session = ChatSession(client, "m", "sys")
    with pytest.raises(KeyboardInterrupt):
        for _ in run_with_tools(session, registry, "Q"):
            pass
    assert [m.role for m in session.messages] == ["system"] and handler.calls == [1]
    sent, *_ = ask(registry, call(5), ["ok"], session=session, text="Q2")
    assert sent == ["Tool result from probe:\nAttempt 1 of 3 · ran 5"]
