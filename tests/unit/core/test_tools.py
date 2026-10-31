"""T18 behavior with local scripted replies and real spawned handlers."""

import json
import math
import multiprocessing
import os
import time

import pytest

from fakes import FakeClient
from tool_handlers import exercise
from sensai.chat.blocks import BlockReader, split_block
from sensai.chat.saved_sessions import first_exchange
from sensai.chat.session import ChatSession
from sensai.core import isolation
from sensai.core.cancellation import CancellationToken, OperationCancelled, OperationTimedOut
from sensai.core.errors import LLMError
from sensai.core.ports import ApprovalDecision, ToolCall, ToolDefinition, ToolResult
from sensai.tools import CALCULATE, ToolRegistry, calculate, parse_tool_call, run_with_tools, tool_instructions


def collect(stream):
    chunks = []
    while True:
        try:
            chunks.append(next(stream))
        except StopIteration as stopped:
            return "".join(chunks), stopped.value


def registry(**settings):
    tools = ToolRegistry()
    tools.register(ToolDefinition("test", "Test handler"), exercise, **settings)
    return tools


def test_block_reader_all_chunk_boundaries_and_final_non_tool():
    # Build with json.dumps so the quoted brace tests actual JSON escaping.
    reply = 'Visible { inline }\n' + json.dumps({"tool": "test", "arguments": {"value": 'é } "'}}) + '  \n'
    for boundary in range(len(reply) + 1):
        reader = BlockReader()
        shown = reader.feed(reply[:boundary]) + reader.feed(reply[boundary:])
        visible, block = reader.finish()
        assert visible == 'Visible { inline }\n'
        assert shown == visible
        assert block == {"tool": "test", "arguments": {"value": 'é } "'}}
    assert split_block('Answer\n{\n"payload": {"x": 1}\n}\n') == ('Answer\n', {"payload": {"x": 1}})


@pytest.mark.parametrize("reply", [
    'inline {"tool":"x"}', ' {"x": 1}', '{invalid}', '{"n": NaN}',
    '{"n": Infinity}', '{"n": -Infinity}', '{"n": 1e999}', '{"x": 1}\nmore text',
    'Ordinary {braces}\n', '{"x": 1} suffix',
])
def test_invalid_nonfinal_and_inline_objects_stay_visible(reply):
    reader = BlockReader()
    shown = "".join(reader.feed(char) for char in reply)
    visible, block = reader.finish()
    assert shown + visible[len(shown):] == reply
    assert block is None


def test_reader_releases_nonfinal_object_and_finds_later_final_block():
    reader = BlockReader()
    assert reader.feed('Prefix\n{"x": 1}') == 'Prefix\n'
    assert reader.feed('\nMore text\n') == '{"x": 1}\nMore text\n'
    assert reader.feed('{"payload": 2}') == ''
    assert reader.finish() == ('Prefix\n{"x": 1}\nMore text\n', {"payload": 2})
    assert split_block('{invalid\n{"payload": 2}') == ('{invalid\n', {"payload": 2})


def test_reader_releases_closed_invalid_braces_before_the_stream_ends():
    reader = BlockReader()
    assert reader.feed('{ordinary braces}\nNext sentence') == '{ordinary braces}\nNext sentence'
    assert reader.feed('\n{"tool":"test"}') == '\n'
    assert reader.finish() == ('{ordinary braces}\nNext sentence\n', {"tool": "test"})


@pytest.mark.parametrize("arguments", [
    {"x": math.nan}, {"x": math.inf}, {"x": (1, 2)}, {1: "x"}, {"x": object()},
])
def test_direct_json_trust_boundary(arguments):
    with pytest.raises(ValueError):
        parse_tool_call({"tool": "test", "arguments": arguments})
    assert registry().execute(ToolCall("test", arguments)).error


@pytest.mark.parametrize("block", [{}, {"tool": " "}, {"tool": 1}, {"tool": "x", "arguments": []}])
def test_malformed_calls(block):
    with pytest.raises(ValueError):
        parse_tool_call(block)


def test_calls_and_instructions_keep_names_and_json():
    assert parse_tool_call({"tool": "calculate"}) == ToolCall("calculate", {})
    assert json.dumps(CALCULATE.parameters) in tool_instructions([CALCULATE])
    assert "calculate" in tool_instructions([CALCULATE])


@pytest.mark.parametrize("settings", [
    {"timeout": 0}, {"timeout": -1}, {"timeout": True}, {"timeout": math.nan},
    {"timeout": math.inf}, {"max_calls": -1}, {"max_calls": True}, {"max_calls": 1.5},
])
def test_registration_rejects_invalid_settings(settings):
    with pytest.raises(ValueError):
        registry(**settings)


def test_registration_names_order_callability_and_pickleability():
    tools = registry()
    with pytest.raises(ValueError):
        tools.register(ToolDefinition("test", "duplicate"), exercise)
    with pytest.raises(ValueError):
        tools.register(ToolDefinition(" ", "blank"), exercise)
    with pytest.raises(ValueError):
        tools.register(ToolDefinition("bad", "noncallable"), None)
    with pytest.raises(ValueError, match="pickleable"):
        tools.register(ToolDefinition("local", "closure"), lambda args, token: ToolResult(""))
    tools.register(CALCULATE, calculate)
    assert [d.name for d in tools.definitions()] == ["test", "calculate"]


def test_schema_required_basic_types_and_bool_distinct_from_number():
    tools = ToolRegistry()
    definition = ToolDefinition("typed", "Typed", {"required": ["n"], "properties": {
        "n": {"type": "number"}, "i": {"type": "integer"}, "s": {"type": "string"},
        "b": {"type": "boolean"}, "a": {"type": "array"}, "o": {"type": "object"},
        "z": {"type": "null"},
    }})
    tools.register(definition, exercise, timeout=None)
    assert tools.execute(ToolCall("typed", {})).error
    for args in ({"n": True}, {"n": 1, "i": False}, {"n": 1, "s": 1}, {"n": 1, "b": 1},
                 {"n": 1, "a": {}}, {"n": 1, "o": []}, {"n": 1, "z": 0}):
        assert tools.execute(ToolCall("typed", args)).error
    assert tools.execute(ToolCall("typed", {"n": 1.5, "i": 1, "b": True, "z": None})) == ToolResult("complete")


@pytest.mark.parametrize("action", ["error", "raise", "invalid", "invalid_field"])
def test_spawned_results_keep_errors_and_validate_handler_results(action):
    result = registry().execute(ToolCall("test", {"action": action}))
    assert result.error
    if action == "error":
        assert result == ToolResult("partial", "explicit failure")


def test_numeric_handler_runs_in_child_and_is_reaped():
    result = registry().execute(ToolCall("test", {"action": "pid"}))
    assert int(result.output) != os.getpid()
    assert not multiprocessing.active_children()


@pytest.mark.parametrize("action, error", [
    ("timeout", OperationTimedOut), ("cancel", OperationCancelled),
])
def test_handler_control_exceptions_survive_transport(action, error):
    with pytest.raises(error) as caught:
        registry().execute(ToolCall("test", {"action": action}))
    assert not isinstance(caught.value, LLMError)
    assert not multiprocessing.active_children()


def test_early_handler_timeout_survives_slow_cleanup(monkeypatch):
    original = isolation._stop
    def slow_stop(process):
        original(process)
        time.sleep(.4)
    monkeypatch.setattr(isolation, "_stop", slow_stop)
    with pytest.raises(OperationTimedOut, match="handler deadline"):
        registry(timeout=.4).execute(ToolCall("test", {"action": "timeout"}))


def test_local_timeout_is_result_but_global_timeout_and_cancel_propagate():
    assert registry(timeout=.2).execute(ToolCall("test", {"action": "block"})).error
    with pytest.raises(OperationTimedOut):
        registry(timeout=5).execute(ToolCall("test", {"action": "block"}),
                                   CancellationToken(time.monotonic() + .2))
    token = CancellationToken()
    token.cancel()
    with pytest.raises(OperationCancelled):
        registry().execute(ToolCall("test", {}), token)


def test_local_expiry_rechecks_global_after_cleanup(monkeypatch):
    token = CancellationToken()
    original = isolation._stop
    def stop_and_cancel(process):
        original(process)
        token.cancel()
    monkeypatch.setattr(isolation, "_stop", stop_and_cancel)
    with pytest.raises(OperationCancelled):
        registry(timeout=.1).execute(ToolCall("test", {"action": "block"}), token)


def test_approval_and_interactive_handler_pause_original_deadline_without_polling():
    polls = []
    token = CancellationToken(time.monotonic() + .1, lambda: polls.append("poll") or False)
    old_deadline = token.deadline
    observed = []
    def read(prompt):
        assert token.deadline is None
        before = len(polls)
        time.sleep(.12)
        assert len(polls) == before
        return "OUi"
    def interactive(args, received):
        assert received is token
        assert received.deadline is None
        before = len(polls)
        time.sleep(.12)
        assert len(polls) == before
        observed.append(os.getpid())
        return ToolResult("user answer")
    tools = ToolRegistry(read=read)
    tools.register(ToolDefinition("ask", "Ask"), interactive, timeout=None, confirm=True)
    assert tools.execute(ToolCall("ask", {}), token) == ToolResult("user answer")
    assert observed == [os.getpid()]
    assert token.deadline >= old_deadline + .24


def test_approval_request_refusal_counting_and_zero_calls():
    requests = []
    class Approval:
        def request(self, request):
            requests.append(request)
            return ApprovalDecision(False)
    tools = ToolRegistry(Approval())
    tools.register(ToolDefinition("test", "Reason"), exercise, confirm=True, max_calls=1)
    assert tools.execute(ToolCall("test", {"x": 1})).error
    assert requests[0].action == "test" and requests[0].reason == "Reason"
    assert json.loads(requests[0].resource) == {"x": 1}
    assert tools.execute(ToolCall("test", {})).error == (
        "Stopped after 1 attempt: answer with the last result or error, without calling test again.")
    assert len(requests) == 1
    disabled = registry(max_calls=0)
    assert disabled.execute(ToolCall("test", {})).error == "tool call limit reached"
    refusing = ToolRegistry(read=lambda _: (_ for _ in ()).throw(EOFError()))
    refusing.register(ToolDefinition("test", "Reason"), exercise, confirm=True)
    assert "refused" in refusing.execute(ToolCall("test", {})).error


def test_round_limit_malformed_unknown_final_block_and_observer_once():
    client = FakeClient(['Before\n{"tool":0}'], ['{"tool":"missing"}'], ['Final\n{"tool":"test"}'])
    session = ChatSession(client, "model", "system")
    seen = []
    visible, result = collect(run_with_tools(session, registry(), "Question", max_rounds=2,
                                            on_tool=lambda call, result: seen.append((call, result))))
    assert visible == 'Before\nFinal\n'
    assert result == ('Final\n', None)
    assert [call.name for call, _ in seen] == ["<invalid>", "missing"]
    assert all(result.error for _, result in seen)
    assert len(client.calls) == 3
    assert client.calls[-1][-1].startswith("Tool error from missing:")
    assert "final answer without tools" in client.calls[-1][-1]


def test_per_question_counts_reset_and_bad_arguments_count():
    tools = ToolRegistry()
    tools.register(CALCULATE, calculate, max_calls=1)
    client = FakeClient(['{"tool":"calculate","arguments":{}}'],
                        ['{"tool":"calculate","arguments":{"expression":"1+1"}}'], ['done'],
                        ['{"tool":"calculate","arguments":{"expression":"2+2"}}'], ['four'])
    session = ChatSession(client, "m", "sys")
    seen = []
    collect(run_with_tools(session, tools, "first", on_tool=lambda call, result: seen.append(result)))
    assert "required" in seen[0].error and seen[1].error.startswith("Stopped after 1 attempt:")
    collect(run_with_tools(session, tools, "second", on_tool=lambda call, result: seen.append(result)))
    assert seen[-1] == ToolResult("4")


@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_bad_max_rounds(value):
    session = ChatSession(FakeClient(), "m", "sys")
    with pytest.raises(ValueError):
        next(run_with_tools(session, registry(), "q", max_rounds=value))
    assert len(session.messages) == 1


def test_non_tool_block_ends_question_and_returns_full_visible_reply():
    session = ChatSession(FakeClient(['A', 'nswer\n{"payload": 1}']), "m", "sys")
    assert collect(run_with_tools(session, registry(), "q")) == ('Answer\n', ('Answer\n', {"payload": 1}))


@pytest.mark.parametrize("failure", [OperationCancelled(), OperationTimedOut(), LLMError(), KeyboardInterrupt()])
def test_all_question_history_rolls_back_after_a_completed_tool_round(failure):
    class FailingClient(FakeClient):
        def stream(self, model, messages, cancellation=None):
            if self.calls:
                yield 'partial'
                raise failure
            yield from super().stream(model, messages, cancellation)
    session = ChatSession(FailingClient(['{"tool":"test"}']), "m", "sys")
    previous = list(session.messages)
    with pytest.raises(type(failure)):
        collect(run_with_tools(session, registry(timeout=None), "q"))
    assert session.messages == previous


def test_generator_close_closes_backend_before_all_history_rollback():
    closed = []
    class Client(FakeClient):
        def stream(self, model, messages, cancellation=None):
            if self.calls:
                try:
                    yield "partial"
                finally:
                    closed.append(len(session.messages))
                return
            yield from super().stream(model, messages, cancellation)
    session = ChatSession(Client(['{"tool":"test"}']), "m", "sys")
    stream = run_with_tools(session, registry(timeout=None), "q")
    assert next(stream) == 'partial'
    stream.close()
    assert closed == [4]  # system + completed round + active tool-result user message
    assert len(session.messages) == 1


def test_observer_failure_rolls_back_question():
    session = ChatSession(FakeClient(['{"tool":"test"}']), "m", "sys")
    def observer(call, result):
        raise RuntimeError("observer failed")
    with pytest.raises(RuntimeError, match="observer failed"):
        collect(run_with_tools(session, registry(timeout=None), "q", on_tool=observer))
    assert len(session.messages) == 1


@pytest.mark.parametrize("expression, expected", [("(2 + 3) * -4 / 2", "-10.0"), ("+2-1", "1")])
def test_safe_calculator(expression, expected):
    tools = ToolRegistry()
    tools.register(CALCULATE, calculate)
    assert tools.execute(ToolCall("calculate", {"expression": expression})) == ToolResult(expected)


@pytest.mark.parametrize("expression", ["True", "abs(-1)", "a", "2**4", "1//2", "(1).__class__", "1/0", "1e999", "9" * 1025])
def test_calculator_rejects_unsupported_or_nonfinite_expressions(expression):
    with pytest.raises((ValueError, ZeroDivisionError)):
        calculate({"expression": expression})


def test_title_skips_tool_rounds_and_uses_final_visible_answer():
    session = ChatSession(FakeClient(['Checking\n{"tool":"test"}'], ['The final answer']), "m", "sys")
    collect(run_with_tools(session, registry(timeout=None), "Original question"))
    assert first_exchange(session.messages) == ("Original question", "The final answer")


def test_calculator_accepts_large_finite_integer_within_expression_limit():
    expression = "9" * 400
    assert calculate({"expression": expression}) == ToolResult(expression)


def test_approval_prompt_escapes_surrogates_from_model_json():
    call = parse_tool_call(json.loads(r'{"tool":"test","arguments":{"value":"\ud800"}}'))

    def read(prompt):
        prompt.encode("utf-8")
        return "yes"

    tools = ToolRegistry(read=read)
    tools.register(ToolDefinition("test", "Reason"),
                   lambda arguments, cancellation: ToolResult("complete"),
                   timeout=None, confirm=True)
    assert tools.execute(call) == ToolResult("complete")
