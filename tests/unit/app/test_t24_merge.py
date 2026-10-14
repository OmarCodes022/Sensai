"""The launcher preserves persona context prepared before local or remote chat."""

import importlib.util
import json
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock

import pytest

from fakes import FakeClient
from sensai.app import cli
from sensai.app.personas import PersonaRegistry
from sensai.app.settings import Settings


SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "run_sensai.py"
spec = importlib.util.spec_from_file_location("launcher_t24_merge", SCRIPT)
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


@pytest.mark.parametrize("remote", [False, True], ids=["local", "remote"])
def test_launcher_switches_with_context_loaded_once_before_tunnel(
    monkeypatch, tmp_path, capsys, remote
):
    profiles = [
        {"id": persona_id, "name": persona_id, "tone": "Clear", "role": persona_id,
         "response_scope": "Supplied captions"}
        for persona_id in ("editor", "Review Team")
    ]
    catalogue = tmp_path / "personas.json"
    catalogue.write_text(json.dumps(profiles), encoding="utf-8")
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Shared rules", encoding="utf-8")
    registry = PersonaRegistry(profiles)
    settings = Settings(
        _env_file=None, SENSAI_MODEL="fake-model", SENSAI_PERSONA="editor",
        SENSAI_PERSONAS_FILE=str(catalogue), SENSAI_PROMPT=str(prompt),
        SENSAI_SSH_HOST="alias" if remote else None,
        OLLAMA_HOST="http://127.0.0.1:11435" if remote else "http://127.0.0.1:11434",
    )
    monkeypatch.setattr(launcher, "Settings", lambda: settings)
    load_registry = Mock(wraps=PersonaRegistry.from_file)
    load_prompt = Mock(wraps=cli.load_system_prompt)
    monkeypatch.setattr(PersonaRegistry, "from_file", load_registry)
    monkeypatch.setattr(cli, "load_system_prompt", load_prompt)
    client = FakeClient(["first", " reply"], ["revision"])
    events = []

    def invalidate_loaded_files():
        load_registry.assert_called_once_with(str(catalogue))
        load_prompt.assert_called_once_with(str(prompt))
        catalogue.write_text("invalid JSON", encoding="utf-8")
        prompt.unlink(missing_ok=True)

    @contextmanager
    def tunnel(alias):
        assert alias == "alias"
        invalidate_loaded_files()
        events.append("tunnel opened")
        yield
        events.append("tunnel closed")

    def create_client(client_settings):
        assert client_settings.host == settings.host
        assert events == (["tunnel opened"] if remote else [])
        invalidate_loaded_files()
        events.append("client created")
        return client

    def forbidden(*args, **kwargs):
        pytest.fail("No real SSH or HTTP is allowed")

    monkeypatch.setattr(launcher, "ssh_tunnel", tunnel)
    monkeypatch.setattr(launcher, "HTTPConnection", forbidden)
    monkeypatch.setattr(launcher.subprocess, "Popen", forbidden)
    monkeypatch.setattr(cli, "create_client", create_client)

    class Terminal:
        def __enter__(self):
            self.inputs = iter(["Draft", "/persona", "/persona Review Team", "Revise", "exit"])
            return self

        def __exit__(self, *args):
            pass

        def read(self, prompt):
            return next(self.inputs)

        def cancel_requested(self):
            return False

    monkeypatch.setattr(cli, "TerminalInput", Terminal)
    assert launcher.main([]) == 0
    assert events == (["tunnel opened", "client created", "tunnel closed"]
                      if remote else ["client created"])
    assert client.calls == [
        ["Shared rules\n\n" + registry.get("editor").system_prompt, "Draft"],
        ["Shared rules\n\n" + registry.get("Review Team").system_prompt,
         "Draft", "first reply",
         "Shared rules\n\n" + registry.get("Review Team").system_prompt, "Revise"],
    ]
    load_registry.assert_called_once()
    load_prompt.assert_called_once()
    output = capsys.readouterr().out
    assert "Review Team: Review Team" in output
    assert "Persona sélectionnée : Review Team" in output
    assert "first reply" in output and "revision" in output
