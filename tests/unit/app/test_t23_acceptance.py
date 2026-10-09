"""Independent startup and REPL checks using only local scripted clients."""

import json

import pytest

from fakes import FakeClient
from sensai.app import cli
from sensai.app.settings import Settings


@pytest.fixture(autouse=True)
def isolated_configuration(monkeypatch):
    for name in ("SENSAI_MODEL", "SENSAI_PERSONA", "SENSAI_PERSONAS_FILE", "SENSAI_PROMPT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(cli, "Settings", lambda: Settings(_env_file=None))


def custom_profile(persona_id="editor"):
    return {
        "id": persona_id,
        "name": "Édition locale",
        "tone": "Direct",
        "role": "Revise draft captions",
        "response_scope": "Caption revisions only",
    }


def test_main_cli_overrides_environment_catalogue_and_selection(monkeypatch, tmp_path):
    catalogue = tmp_path / "profiles.json"
    catalogue.write_text(json.dumps([custom_profile()]), encoding="utf-8")
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Keep shared approval rules.", encoding="utf-8")
    monkeypatch.setenv("SENSAI_PERSONAS_FILE", str(tmp_path / "missing-env.json"))
    monkeypatch.setenv("SENSAI_PERSONA", "missing-env-persona")
    client = FakeClient(["draft"], ["revision"])
    monkeypatch.setattr(cli, "create_client", lambda settings: client)

    class Terminal:
        def __enter__(self):
            self.inputs = iter(["Write a draft", "Revise it", "exit"])
            return self

        def __exit__(self, *args):
            pass

        def read(self, prompt):
            return next(self.inputs)

        def cancel_requested(self):
            return False

    monkeypatch.setattr(cli, "TerminalInput", Terminal)
    cli.main(["fake-model", "--prompt", str(prompt), "--personas-file", str(catalogue),
              "--persona", "editor"])
    assert len(client.calls) == 2
    transmitted_prompt = client.calls[0][0]
    assert transmitted_prompt.startswith("Keep shared approval rules.\n\nPersona: Édition locale")
    assert "Caption revisions only" in transmitted_prompt
    assert client.calls[1] == [transmitted_prompt, "Write a draft", "draft", "Revise it"]


def test_actual_repl_cancellation_keeps_persona_and_discards_partial_turn(
    monkeypatch, tmp_path, capsys
):
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Shared rules", encoding="utf-8")
    client = FakeClient(["shown partial", "never shown"], ["complete"])
    monkeypatch.setattr(cli, "create_client", lambda settings: client)
    partial_emitted = False

    class Terminal:
        def __enter__(self):
            self.inputs = iter(["Interrupted request", "Next request", "exit"])
            return self

        def __exit__(self, *args):
            pass

        def read(self, prompt):
            nonlocal partial_emitted
            partial_emitted = False
            return next(self.inputs)

        def cancel_requested(self):
            return partial_emitted and len(client.calls) == 1

    original_stream = client.stream

    def stream(model, messages, cancellation=None):
        nonlocal partial_emitted
        for chunk in original_stream(model, messages, cancellation):
            yield chunk
            if len(client.calls) == 1:
                partial_emitted = True

    client.stream = stream
    monkeypatch.setattr(cli, "TerminalInput", Terminal)
    cli.main(["fake-model", "--prompt", str(prompt), "--persona", "analyse"])
    assert len(client.calls) == 2
    assert "Persona: Analyse" in client.calls[0][0]
    assert client.calls[1] == [client.calls[0][0], "Next request"]
    output = capsys.readouterr().out
    assert "shown partial" in output
    assert "Réponse interrompue" in output
    assert "never shown" not in output
    assert "complete" in output


@pytest.mark.parametrize("contents", [
    b"\xff\xfe", b"{invalid JSON", b"[]", b"[null]",
    json.dumps([custom_profile(), custom_profile(" editor ")]).encode(),
    json.dumps([dict(custom_profile(), response_scope=None)]).encode(),
])
def test_bad_catalogue_is_explicit_startup_error_before_model_or_prompt(
    monkeypatch, tmp_path, contents
):
    path = tmp_path / "bad.json"
    path.write_bytes(contents)
    monkeypatch.setattr(cli, "create_client", lambda settings: pytest.fail("model client created"))
    monkeypatch.setattr(cli, "load_system_prompt", lambda path: pytest.fail("prompt loaded"))
    with pytest.raises(SystemExit, match="error: cannot load personas:"):
        cli.main(["fake-model", "--personas-file", str(path)])


def test_listing_custom_environment_catalogue_from_another_cwd(monkeypatch, tmp_path, capsys):
    catalogue = tmp_path / "profiles.json"
    catalogue.write_text(json.dumps([custom_profile()]), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SENSAI_PERSONAS_FILE", str(catalogue))
    monkeypatch.setenv("SENSAI_PERSONA", "unknown-selection")
    monkeypatch.setenv("SENSAI_PROMPT", "missing-prompt.txt")
    monkeypatch.setattr(cli, "create_client", lambda settings: pytest.fail("model client created"))
    monkeypatch.setattr(cli, "load_system_prompt", lambda path: pytest.fail("prompt loaded"))
    cli.main(["--list-personas"])
    assert capsys.readouterr().out.splitlines() == ["editor: Édition locale"]
