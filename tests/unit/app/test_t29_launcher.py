"""The SSH launcher forwards the T29 session options unchanged (modelled on test_t24_merge)."""

import importlib.util
import json
import os
from contextlib import contextmanager
from pathlib import Path

import pytest

from fakes import FakeClient
from sensai.app import cli, conversations
from sensai.app.personas import PersonaRegistry
from sensai.app.settings import Settings
from sensai.memory.storage import StorageRepository

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "run_sensai.py"
spec = importlib.util.spec_from_file_location("launcher_t29", SCRIPT)
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)
PROFILE = "Profil de la créatrice (instructions personnalisées) :\n- ton : direct"


@pytest.fixture(autouse=True)
def no_external_io(monkeypatch):
    for name in list(os.environ):
        if name.startswith("SENSAI_") or name == "OLLAMA_HOST":
            monkeypatch.delenv(name, raising=False)

    def forbidden(*args, **kwargs):
        pytest.fail("No real SSH or HTTP is allowed")

    monkeypatch.setattr(launcher, "HTTPConnection", forbidden)
    monkeypatch.setattr(launcher.subprocess, "Popen", forbidden)


def configure(monkeypatch, tmp_path, remote, events):
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Shared rules", encoding="utf-8")
    settings = Settings(
        _env_file=None, SENSAI_MODEL="fake-model", SENSAI_PROMPT=str(prompt),
        SENSAI_DB=str(tmp_path / "env.db"), SENSAI_CREATOR="env-creator",
        SENSAI_SSH_HOST="alias" if remote else None,
        OLLAMA_HOST="http://127.0.0.1:11435" if remote else "http://127.0.0.1:11434",
    )
    monkeypatch.setattr(launcher, "Settings", lambda: settings)

    @contextmanager
    def tunnel(alias):
        events.append("tunnel opened")
        yield
        events.append("tunnel closed")

    monkeypatch.setattr(launcher, "ssh_tunnel", tunnel)


def terminal(monkeypatch, inputs):
    class Terminal:
        def __enter__(self):
            self.inputs = iter(inputs)
            return self

        def __exit__(self, *args):
            pass

        def read(self, prompt):
            return next(self.inputs)

        def cancel_requested(self):
            return False

    monkeypatch.setattr(cli, "TerminalInput", Terminal)


@pytest.mark.parametrize("remote", [False, True], ids=["local", "remote"])
def test_t29_launcher_forwards_session_options(monkeypatch, tmp_path, capsys, remote):
    events = []
    configure(monkeypatch, tmp_path, remote, events)
    monkeypatch.setattr(conversations, "new_session_id", lambda exists: "k7f2qa")
    profile = tmp_path / "profil.json"
    profile.write_text(json.dumps({"ton": "direct"}), encoding="utf-8")
    database = str(tmp_path / "cli.db")
    client = FakeClient(["R1"], ["R2"])

    def create_client(client_settings):
        events.append("client created")
        return client

    monkeypatch.setattr(cli, "create_client", create_client)
    terminal(monkeypatch, ["Q1", "exit"])
    common = ["--db", database, "--creator", "alice"]
    assert launcher.main([*common, "--profile-file", str(profile), "--persona", "analyse"]) == 0
    terminal(monkeypatch, ["Q2", "exit"])
    assert launcher.main([*common, "--session", "k7f2qa"]) == 0
    expected = ["tunnel opened", "client created", "tunnel closed"] if remote else ["client created"]
    assert events == expected * 2
    system = "Shared rules\n\n" + PROFILE + "\n\n" + PersonaRegistry.from_file().get(
        "analyse").system_prompt
    assert client.calls == [[system, "Q1"], [system, "Q1", "R1", "Q2"]]
    assert "Session k7f2qa — Q1" in capsys.readouterr().out
    with StorageRepository(database) as repository:
        sessions = repository.for_creator("alice").sessions
        assert [m.content for m in sessions.load("k7f2qa").messages] == ["Q1", "R1", "Q2", "R2"]
    assert not (tmp_path / "env.db").exists()

    events.clear()
    monkeypatch.setattr(cli, "create_client", lambda settings: pytest.fail("client created"))
    with pytest.raises(SystemExit, match="unknown session: zzzzzz"):
        launcher.main([*common, "--session", "zzzzzz"])
    assert launcher.main([*common, "--list-sessions", "--host", "http://evil.example"]) == 0
    assert events == []
    assert capsys.readouterr().out.splitlines()[0].startswith("k7f2qa  ")
