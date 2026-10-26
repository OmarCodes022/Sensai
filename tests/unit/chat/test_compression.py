"""chat.compression: when to summarize, where to cut, and keeping history on failure."""

import pytest

from fakes import FakeClient
from sensai.chat import compression
from sensai.chat.session import ChatSession
from sensai.core.cancellation import CancellationToken, OperationCancelled
from sensai.core.errors import LLMError
from sensai.core.messages import Message


def turns(n):
    out = []
    for i in range(n):
        out += [Message(role="user", content=f"q{i}"), Message(role="assistant", content=f"a{i}")]
    return out


def session_with(client, history):
    session = ChatSession(client, "model", "Rules")
    session.messages.extend(history)
    return session


@pytest.mark.parametrize("tokens, expected", [(799, False), (800, True), (1000, True)])
def test_threshold_is_eighty_percent(tokens, expected):
    assert compression.should_compress(tokens, 1000) is expected


def test_estimate_is_characters_over_four():
    assert compression.estimate_tokens([Message(role="user", content="x" * 41)]) == 10


def test_cut_keeps_system_and_last_four_and_needs_two_old_messages():
    system = [Message(role="system", content="Rules")]
    assert compression.choose_cut(system + turns(3)) == 3
    assert compression.choose_cut(system + turns(2)) is None  # only 0 old messages
    assert compression.choose_cut(system + turns(2) + turns(1)[:1]) is None  # 1 old message


@pytest.mark.parametrize("content", [
    'Let me check.\n{"tool": "search", "arguments": {"q": "x"}}',
    '{"tool": "clock"}',
])
def test_cut_never_separates_a_tool_call_from_its_result(content):
    call = Message(role="assistant", content=content)
    result = Message(role="user", content="Tool result: 42")
    history = [Message(role="system", content="Rules"), *turns(2), Message(role="user", content="q"),
               call, result, *turns(1), Message(role="user", content="last")]
    # Plain cut would be 7 = len - 4: summarize the call (index 6), keep its result.
    cut = compression.choose_cut(history)
    assert cut == 6 and history[cut] is call


def test_json_without_tool_key_is_not_a_tool_call():
    assert not compression.is_tool_call(Message(role="assistant", content='Here:\n{"title": "x"}'))
    assert not compression.is_tool_call(Message(role="user", content='{"tool": "x"}'))


def test_compress_replaces_old_messages_with_one_assistant_summary():
    client = FakeClient(["Launch 14 November,", " Calm Barrier Cream."])
    session = session_with(client, turns(4))
    tail = session.messages[-4:]
    assert compression.compress(session, 5)
    assert session.messages[0] == Message(role="system", content="Rules")
    assert session.messages[1] == Message(
        role="assistant", content=f"{compression.SUMMARY_PREFIX}\nLaunch 14 November, Calm Barrier Cream.")
    assert session.messages[2:] == tail
    (request,) = client.requests[0][1]
    assert request.role == "user"
    assert request.content == ("Conversation:\n<<<\nuser: q0\n\nassistant: a0\n\nuser: q1\n\n"
                               f"assistant: a1\n>>>\n\n{compression.SUMMARY_REQUEST}")


def test_earlier_summary_is_kept_verbatim_and_extended():
    client = FakeClient(["Post 2 uses oats."])
    earlier = Message(role="assistant",
                      content=f"{compression.SUMMARY_PREFIX}\nLaunch 14 November, Calm Barrier Cream.")
    session = session_with(client, [earlier, *turns(3)])
    assert compression.compress(session, 4)
    assert session.messages[1].content == (
        f"{compression.SUMMARY_PREFIX}\nLaunch 14 November, Calm Barrier Cream.\nPost 2 uses oats.")
    assert session.messages[2:] == turns(3)[2:]
    (request,) = client.requests[0][1]
    assert "Launch 14 November" not in request.content  # not sent to be re-summarized
    assert "user: q0\n\nassistant: a0" in request.content


@pytest.mark.parametrize("reply", [
    LLMError("connection refused"),
    ["partial", LLMError("dropped")],
    ["   "],
])
def test_failed_or_empty_summary_keeps_full_history(reply):
    session = session_with(FakeClient(reply), turns(4))
    before = list(session.messages)
    assert not compression.compress(session, 5)
    assert session.messages == before


def test_ctrl_c_during_summary_keeps_full_history():
    class Interrupted(FakeClient):
        def stream(self, model, messages, cancellation=None):
            yield "partial"
            raise KeyboardInterrupt

    session = session_with(Interrupted(), turns(4))
    before = list(session.messages)
    assert not compression.compress(session, 5)
    assert session.messages == before


def test_cancelled_summary_keeps_full_history():
    cancelled = iter([False, True, True, True])
    token = CancellationToken(None, lambda: next(cancelled))
    session = session_with(FakeClient(["one", "two"]), turns(4))
    before = list(session.messages)
    assert not compression.compress(session, 5, token)
    assert session.messages == before
