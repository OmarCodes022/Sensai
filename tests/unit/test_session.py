import pytest
from fakes import FakeClient

from sensai.errors import LLMError
from sensai.messages import Message
from sensai.session import ChatSession


def test_starts_with_system_prompt():
    s = ChatSession(FakeClient(), "m", "You are Sensai.")
    assert s.messages == [Message(role="system", content="You are Sensai.")]


def test_streams_chunks_in_order():
    s = ChatSession(FakeClient(["Hel", "lo", "!"]), "m", "sys")
    assert list(s.send("hi")) == ["Hel", "lo", "!"]


def test_history_is_sent_each_turn():
    client = FakeClient(["A1"], ["A2"])
    s = ChatSession(client, "m", "sys")
    list(s.send("Q1"))
    list(s.send("Q2"))
    assert client.calls[1] == ["sys", "Q1", "A1", "Q2"]


@pytest.mark.parametrize("text", ["", "   ", "\n"])
def test_empty_input_rejected(text):
    s = ChatSession(FakeClient(), "m", "sys")
    with pytest.raises(ValueError):
        list(s.send(text))
    assert len(s.messages) == 1


def test_failed_turn_is_rolled_back():
    s = ChatSession(FakeClient(LLMError("boom")), "m", "sys")
    with pytest.raises(LLMError):
        list(s.send("hi"))
    assert len(s.messages) == 1
