"""Empty model replies must not become conversation history."""

import pytest

from fakes import FakeClient
from sensai.app import cli
from sensai.app.personas import PersonaRegistry
from sensai.app.session import ChatSession
from sensai.core.errors import LLMError


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


def test_cli_recovers_from_empty_reply_and_honors_two_persona_switches():
    registry = PersonaRegistry.from_file()
    client = FakeClient(["Je suis Rédaction."], [], ["New", " answer"])
    session = ChatSession(client, "model", "Shared\n\n" + registry.get("redaction").system_prompt)
    inputs = iter([
        "Earlier", "/persona analyse", "Failed", "/persona communaute", "Continue", "exit",
    ])
    output = []
    cli.repl(session, read=lambda _: next(inputs),
             write=lambda text="", **kwargs: output.append(text),
             persona_registry=registry, base_prompt="Shared")

    analyse_prompt = "Shared\n\n" + registry.get("analyse").system_prompt
    communaute_prompt = "Shared\n\n" + registry.get("communaute").system_prompt
    assert client.calls[1] == [
        analyse_prompt, "Earlier", "Je suis Rédaction.", analyse_prompt, "Failed",
    ]
    assert client.calls[2] == [
        communaute_prompt, "Earlier", "Je suis Rédaction.", communaute_prompt, "Continue",
    ]
    assert [message.role for message in client.requests[2][1]] == [
        "system", "user", "assistant", "system", "user",
    ]
    assert session.messages[0].content == communaute_prompt
    assert [message.content for message in session.messages[1:]] == [
        "Earlier", "Je suis Rédaction.", "Continue", "New answer",
    ]
    assert output.count("Persona sélectionnée : analyse") == 1
    assert output.count("Persona sélectionnée : communaute") == 1
    assert sum(text.startswith("error:") and "no visible answer" in text for text in output) == 1
    assert output[-3:-1] == ["New", " answer"]


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
