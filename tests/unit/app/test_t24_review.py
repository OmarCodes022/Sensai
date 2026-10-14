"""Independent interruption checks across persona changes and completed turns."""

import pytest

from fakes import FakeClient
from sensai.app import cli
from sensai.app.personas import PersonaRegistry
from sensai.app.session import ChatSession
from sensai.core import cancellation


@pytest.mark.parametrize("interrupt, notice", [
    ("cancel", "Réponse interrompue"),
    ("timeout", "Délai maximal dépassé"),
])
def test_interrupted_switch_preserves_earlier_turn_and_streaming(monkeypatch, interrupt, notice):
    clock = 0.0
    cancelled = False
    monkeypatch.setattr(cli, "monotonic", lambda: clock)
    monkeypatch.setattr(cancellation, "monotonic", lambda: clock)
    registry = PersonaRegistry.from_file()
    client = FakeClient(["old reply"], ["partial", "discarded"], ["new", " reply"])
    session = ChatSession(client, "model", "Shared")
    inputs = iter([
        "Earlier", "/persona analyse", "Interrupted", "/persona absent",
        "/persona communaute", "Continue", "exit",
    ])
    output = []

    def read(_):
        nonlocal cancelled
        cancelled = False
        return next(inputs)

    def write(text="", **kwargs):
        nonlocal clock, cancelled
        output.append(text)
        if text == "partial":
            if interrupt == "cancel":
                cancelled = True
            else:
                clock += 121.0

    cli.repl(session, read=read, write=write, cancel_requested=lambda: cancelled,
             persona_registry=registry, base_prompt="Shared")

    analyse = "Shared\n\n" + registry.get("analyse").system_prompt
    communaute = "Shared\n\n" + registry.get("communaute").system_prompt
    assert client.calls == [
        ["Shared", "Earlier"],
        [analyse, "Earlier", "old reply", analyse, "Interrupted"],
        [communaute, "Earlier", "old reply", communaute, "Continue"],
    ]
    assert [message.content for message in session.messages[1:]] == [
        "Earlier", "old reply", "Continue", "new reply",
    ]
    assert "discarded" not in output
    assert any(notice in text for text in output)
    assert output[-3:-1] == ["new", " reply"]
