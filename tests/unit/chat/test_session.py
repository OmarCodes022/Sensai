import pytest
from fakes import FakeClient

from sensai.core.errors import LLMError
from sensai.core.messages import Message
from sensai.chat.session import ChatSession


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


def test_system_prompt_replacement_preserves_completed_history_and_prior_request():
    client = FakeClient(["A1"], ["A2"])
    session = ChatSession(client, "m", "original")
    list(session.send("Q1"))
    history = session.messages[1:]
    session.set_system_prompt(" replacement ")
    assert session.messages[0] == Message(role="system", content=" replacement ")
    assert session.messages[1:] == history
    assert all(current is prior for current, prior in zip(session.messages[1:], history))
    assert client.requests[0][1][0].content == "original"
    list(session.send("Q2"))
    assert client.calls[1] == [" replacement ", "Q1", "A1", " replacement ", "Q2"]


@pytest.mark.parametrize("prompt", [None, 42, "", " \t\n"])
def test_invalid_system_prompt_does_not_mutate_history(prompt):
    session = ChatSession(FakeClient(), "m", "original")
    before = list(session.messages)
    with pytest.raises(ValueError, match="nonempty string"):
        session.set_system_prompt(prompt)
    assert session.messages == before


# Empty model replies must not become conversation history.

@pytest.mark.parametrize("empty_reply", [[], [""], [" ", "\t", "\n"]])
def test_empty_turn_rolls_back_without_losing_history_or_selected_persona(empty_reply):
    client = FakeClient(["Earlier answer"], empty_reply, ["Next", " answer"])
    session = ChatSession(client, "model", "Shared")
    list(session.send("Earlier question"))
    session.set_system_prompt("Shared\nCurrent persona")
    completed_history = list(session.messages)

    with pytest.raises(LLMError, match="no visible answer"):
        list(session.send("Failed question"))

    assert session.messages == completed_history
    assert list(session.send("Next question")) == ["Next", " answer"]
    assert client.calls[-1] == [
        "Shared\nCurrent persona", "Earlier question", "Earlier answer",
        "Shared\nCurrent persona", "Next question",
    ]
    assert [message.content for message in session.messages] == [
        "Shared\nCurrent persona", "Earlier question", "Earlier answer",
        "Next question", "Next answer",
    ]


def test_current_role_reminder_is_request_only_and_does_not_accumulate():
    client = FakeClient(["First"], ["Second"], ["Third"], ["Fourth"])
    session = ChatSession(client, "model", "Initial role")
    with pytest.raises(ValueError):
        session.set_system_prompt("")
    list(session.send("One"))
    assert [message.role for message in client.requests[0][1]] == ["system", "user"]

    session.set_system_prompt("New role")
    list(session.send("Two"))
    session.set_system_prompt("Current role")
    list(session.send("Three"))
    with pytest.raises(ValueError):
        session.set_system_prompt("\t")
    list(session.send("Four"))

    for request, active_role in zip(client.requests[1:], ["New role", "Current role", "Current role"]):
        messages = request[1]
        assert [message.content for message in messages if message.role == "system"] == [
            active_role, active_role,
        ]
        assert messages[-2].role == "system"
        assert messages[-1].role == "user"
    assert [message.content for message in session.messages if message.role == "system"] == [
        "Current role",
    ]
    assert [message.content for message in session.messages[1:]] == [
        "One", "First", "Two", "Second", "Three", "Third", "Four", "Fourth",
    ]
