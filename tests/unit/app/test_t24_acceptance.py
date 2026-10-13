"""Persona switches use the loaded catalogue and preserve complete chat turns."""

import json

import pytest

from fakes import FakeClient
from sensai.app import cli
from sensai.app.personas import PersonaRegistry
from sensai.app.session import ChatSession
from sensai.app.settings import Settings
from sensai.core.cancellation import OperationCancelled
from sensai.core.errors import LLMError


@pytest.mark.parametrize("initial_persona", [None, "editor"])
def test_main_switches_cached_custom_profiles_without_losing_history(
    monkeypatch, tmp_path, capsys, initial_persona
):
    profiles = [
        {"id": persona_id, "name": name, "tone": "Clear", "role": name,
         "response_scope": scope}
        for persona_id, name, scope in [
            ("editor", "Édition", "Draft captions"),
            ("Review Team", "Review", "Review supplied captions"),
        ]
    ]
    catalogue = tmp_path / "personas.json"
    catalogue.write_text(json.dumps(profiles), encoding="utf-8")
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("Shared custom instructions.", encoding="utf-8")
    registry = PersonaRegistry(profiles)
    client = FakeClient(["first", " reply"], ["revision"], ["last"])
    monkeypatch.setattr(cli, "Settings", lambda: Settings(_env_file=None, SENSAI_PERSONA=None,
                                                         SENSAI_PERSONAS_FILE=None))
    monkeypatch.setattr(cli, "create_client", lambda _: client)

    class Terminal:
        def __enter__(self):
            self.inputs = iter([
                "Draft", " /persona ", "/persona absent", "/persona redaction",
                "\t/persona\tReview Team  ", "Revise", "/persona editor",
                "/persona editor", "Finish", "exit",
            ])
            return self

        def __exit__(self, *args):
            pass

        def read(self, prompt):
            text = next(self.inputs)
            if text == " /persona ":
                catalogue.write_text("invalid JSON after startup", encoding="utf-8")
                prompt_file.write_text("Changed after startup", encoding="utf-8")
            return text

        def cancel_requested(self):
            return False

    monkeypatch.setattr(cli, "TerminalInput", Terminal)
    args = ["fake-model", "--prompt", str(prompt_file), "--personas-file", str(catalogue)]
    if initial_persona:
        args.extend(["--persona", initial_persona])
    cli.main(args)

    base = "Shared custom instructions."
    initial = base if initial_persona is None else base + "\n\n" + registry.get("editor").system_prompt
    reviewer = base + "\n\n" + registry.get("Review Team").system_prompt
    editor = base + "\n\n" + registry.get("editor").system_prompt
    assert client.calls == [
        [initial, "Draft"],
        [reviewer, "Draft", "first reply", "Revise"],
        [editor, "Draft", "first reply", "Revise", "revision", "Finish"],
    ]
    assert [message.role for message in client.requests[2][1]] == [
        "system", "user", "assistant", "user", "assistant", "user",
    ]
    output = capsys.readouterr().out
    assert "editor: Édition\nReview Team: Review" in output
    assert "error: unknown persona: absent" in output
    assert "error: unknown persona: redaction" in output
    assert "Persona sélectionnée : Review Team" in output
    assert "first reply" in output and "revision" in output and "last" in output


def test_invalid_and_listing_commands_leave_existing_history_untouched(capsys):
    client = FakeClient(["reply"])
    session = ChatSession(client, "model", "Shared")
    list(session.send("Question"))
    before = list(session.messages)
    inputs = iter(["/persona", "/persona absent", "/persona redaction extra", "exit"])
    cli.repl(session, read=lambda _: next(inputs), persona_registry=PersonaRegistry.from_file(),
             base_prompt="Shared")
    assert session.messages == before
    assert len(client.calls) == 1
    assert "error: unknown persona: redaction extra" in capsys.readouterr().out


@pytest.mark.parametrize("failure, notice", [
    (OperationCancelled("cancelled"), "Réponse interrompue"),
    (LLMError("broken stream"), "error: broken stream"),
])
def test_switched_persona_survives_interrupted_stream_and_next_switch(failure, notice, capsys):
    registry = PersonaRegistry.from_file()
    client = FakeClient(["partial", failure], ["complete"])
    session = ChatSession(client, "model", "Shared")
    inputs = iter([
        "/persona analyse", "Interrupted", "/persona communaute", "Next", "exit",
    ])
    cli.repl(session, read=lambda _: next(inputs), persona_registry=registry, base_prompt="Shared")
    assert client.calls == [
        ["Shared\n\n" + registry.get("analyse").system_prompt, "Interrupted"],
        ["Shared\n\n" + registry.get("communaute").system_prompt, "Next"],
    ]
    assert [message.content for message in session.messages[1:]] == ["Next", "complete"]
    output = capsys.readouterr().out
    assert "partial" in output and notice in output and "complete" in output


def test_legacy_repl_rejects_persona_command_without_model_call(capsys):
    client = FakeClient(["reply"])
    session = ChatSession(client, "model", "Shared")
    inputs = iter(["/persona analyse", "/personality", "exit"])
    cli.repl(session, read=lambda _: next(inputs))
    assert client.calls == [["Shared", "/personality"]]
    assert "error: persona selection is unavailable" in capsys.readouterr().out
