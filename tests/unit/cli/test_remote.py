"""cli.remote (sensai-remote) contracts, without contacting Ollama or starting real SSH."""
import json
import subprocess
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock

import pytest

from fakes import FakeClient, scripted_terminal
from sensai.cli import main as cli
from sensai.chat import saved_sessions
from sensai.cli import remote
from sensai.chat.personas import PersonaRegistry
from sensai.settings import Settings
from sensai.memory.sqlite_store import StorageRepository


ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def no_external_io(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Tests must not contact HTTP or run real SSH")

    monkeypatch.setattr(remote, "HTTPConnection", forbidden)
    monkeypatch.setattr(remote.subprocess, "Popen", forbidden)
    monkeypatch.setattr(remote.subprocess, "run", forbidden)


def configure(monkeypatch, *, alias=None, host="http://127.0.0.1:11434"):
    settings = Settings(_env_file=None, SENSAI_MODEL="configured-model",
                        SENSAI_SSH_HOST=alias, OLLAMA_HOST=host,
                        SENSAI_PROMPT=str(ROOT / "src/sensai/chat/system_prompt.txt"))
    monkeypatch.setattr(remote, "Settings", lambda: settings)
    return settings


@pytest.mark.parametrize("case,expected", [
    ("unknown-persona", "unknown persona"),
    ("missing-prompt", "cannot read system prompt"),
    ("unreadable-prompt", "cannot read system prompt"),
    ("invalid-catalogue", "cannot load personas"),
])
def test_local_input_errors_precede_remote_io(monkeypatch, tmp_path, case, expected):
    configure(monkeypatch, alias="sensai-windows", host="http://127.0.0.1:11435")
    probe = Mock(side_effect=AssertionError("network attempted before local validation"))
    monkeypatch.setattr(remote, "ollama_running", probe)
    if case == "unknown-persona":
        args = ["--persona", "does-not-exist"]
    elif case == "missing-prompt":
        args = ["--prompt", str(tmp_path / "missing.txt")]
    elif case == "unreadable-prompt":
        args = ["--prompt", str(tmp_path)]
    else:
        catalogue = tmp_path / "invalid.json"
        catalogue.write_text("{}")
        args = ["--personas-file", str(catalogue)]
    with pytest.raises(SystemExit, match=expected):
        remote.main(args)
    probe.assert_not_called()


@pytest.mark.parametrize("alias", [None, ""])
def test_local_launch_does_not_probe_or_start_ssh(monkeypatch, alias):
    configure(monkeypatch, alias=alias)
    run = Mock()
    monkeypatch.setattr(remote.cli, "run_chat", run)
    args = ["selected-model", "--persona", "redaction"]
    assert remote.main(args) == 0
    run.assert_called_once()
    assert run.call_args.args[1].model == args[0]
    assert run.call_args.args[2]


def test_help_never_connects_even_with_bad_remote_configuration(monkeypatch, capsys):
    configure(monkeypatch, alias="-invalid", host="https://remote.example")
    with pytest.raises(SystemExit) as result:
        remote.main(["--help"])
    assert result.value.code == 0
    assert "--persona" in capsys.readouterr().out


def test_list_personas_needs_no_model_or_connection(monkeypatch, capsys):
    settings = Settings(_env_file=None, SENSAI_MODEL=None, SENSAI_SSH_HOST="-invalid",
                        OLLAMA_HOST="https://remote.example", SENSAI_PERSONAS_FILE=None)
    monkeypatch.setattr(remote, "Settings", lambda: settings)
    assert remote.main(["--list-personas"]) == 0
    assert "redaction: Rédaction" in capsys.readouterr().out


@pytest.mark.parametrize("host", ["http://127.0.0.1:11435", "http://127.0.0.1:11435/"])
def test_cli_host_override_controls_remote_connection(monkeypatch, host):
    configure(monkeypatch, alias="sensai-windows", host="http://wrong.example")
    seen = []
    from contextlib import contextmanager

    @contextmanager
    def tunnel(alias):
        seen.append(alias)
        yield

    monkeypatch.setattr(remote, "ssh_tunnel", tunnel)
    run = Mock()
    monkeypatch.setattr(remote.cli, "run_chat", run)
    args = ["cli-model", "--host", host, "--persona", "analyse"]
    assert remote.main(args) == 0
    assert seen == ["sensai-windows"]
    run.assert_called_once()
    assert run.call_args.args[1].model == args[0]
    assert run.call_args.args[2]


@pytest.mark.parametrize("host", [
    "http://localhost:11435", "http://127.0.0.1:11434", "https://127.0.0.1:11435",
    "http://127.0.0.1:11435/path", "http://user@127.0.0.1:11435", "http://evil.example",
])
def test_remote_host_must_be_exact_loopback_endpoint(monkeypatch, capsys, host):
    configure(monkeypatch, alias="sensai-windows", host="http://127.0.0.1:11435")
    monkeypatch.setattr(remote.cli, "run_chat", lambda *args: pytest.fail("CLI was run"))
    assert remote.main(["--host", host]) == 1
    assert "requires OLLAMA_HOST/--host" in capsys.readouterr().err


@pytest.mark.parametrize("alias", ["-oProxyCommand=bad", "two words", "alias\nother", "alias\x00", "\t"])
def test_invalid_ssh_alias_fails_before_network(monkeypatch, capsys, alias):
    configure(monkeypatch, alias=alias, host="http://127.0.0.1:11435")
    monkeypatch.setattr(remote.cli, "run_chat", lambda *args: pytest.fail("CLI was run"))
    assert remote.main([]) == 1
    assert "SENSAI_SSH_HOST" in capsys.readouterr().err


def test_environment_overrides_dotenv_and_cli_overrides_environment(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "SENSAI_SSH_HOST=file-alias\nOLLAMA_HOST=http://127.0.0.1:11434\nSENSAI_MODEL=file-model\n"
    )
    monkeypatch.setenv("SENSAI_SSH_HOST", "env-alias")
    monkeypatch.setenv("OLLAMA_HOST", "http://wrong.example")
    monkeypatch.setenv("SENSAI_MODEL", "env-model")
    settings = Settings()
    assert settings.ssh_host == "env-alias"
    args = remote.cli.parse_args(settings, ["cli-model", "--host", "http://127.0.0.1:11435"])
    assert (args.model, args.host) == ("cli-model", "http://127.0.0.1:11435")
    monkeypatch.setenv("SENSAI_SSH_HOST", "")
    assert not Settings().ssh_host


def http_connection(monkeypatch, *, status=200, body=b'{"models": []}'):
    connection = Mock()
    response = connection.getresponse.return_value
    response.status = status
    response.read.return_value = body
    constructor = Mock(return_value=connection)
    monkeypatch.setattr(remote, "HTTPConnection", constructor)
    return constructor, connection


def test_probe_uses_only_bounded_loopback_http(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://must-not-be-used.example")
    constructor, connection = http_connection(monkeypatch)
    assert remote.ollama_running() is True
    constructor.assert_called_once_with("127.0.0.1", 11435, timeout=2)
    connection.request.assert_called_once_with("GET", "/api/tags")
    connection.getresponse.return_value.read.assert_called_once_with(1024 * 1024 + 1)
    connection.close.assert_called_once_with()


def test_only_connection_refusal_means_no_existing_tunnel(monkeypatch):
    _, connection = http_connection(monkeypatch)
    connection.connect.side_effect = ConnectionRefusedError()
    assert remote.ollama_running() is False
    connection.close.assert_called_once_with()


@pytest.mark.parametrize("status,body", [
    (302, b'{"models": []}'), (500, b'{"models": []}'), (200, b'not json'),
    (200, b'[]'), (200, b'{}'), (200, b'{"models": {}}'),
    (200, b'x' * (1024 * 1024 + 1)),
    pytest.param(200, b'{"models":' + b'[' * 100000 + b'0' + b']' * 100000 + b'}',
                 id="deeply-nested-json"),
])
def test_unrelated_or_redirecting_endpoint_is_not_reused(monkeypatch, status, body):
    _, connection = http_connection(monkeypatch, status=status, body=body)
    with pytest.raises(remote.RemoteError, match="port 11435"):
        remote.ollama_running()
    connection.close.assert_called_once_with()


@pytest.mark.parametrize("error", [TimeoutError(), ConnectionResetError(), OSError("failure")])
def test_probe_failure_cannot_trigger_an_ssh_fallback(monkeypatch, error):
    _, connection = http_connection(monkeypatch)
    connection.connect.side_effect = error
    with pytest.raises(remote.RemoteError):
        remote.ollama_running()
    connection.close.assert_called_once_with()


def test_preexisting_tunnel_is_never_closed(monkeypatch):
    monkeypatch.setattr(remote, "ollama_running", lambda: True)
    monkeypatch.setattr(remote, "_stop_tunnel", lambda *args: pytest.fail("Existing tunnel closed"))
    with remote.ssh_tunnel("sensai-windows"):
        pass


def owned_process(monkeypatch):
    process = Mock()
    process.poll.return_value = None
    process.wait.return_value = 0
    monkeypatch.setattr(remote, "ollama_running", lambda: False)
    monkeypatch.setattr(remote, "_start_tunnel", lambda _: process)
    monkeypatch.setattr(remote, "_wait_for_ollama", lambda _: None)
    return process


@pytest.mark.parametrize("failure", [None, RuntimeError("chat failed"), KeyboardInterrupt()])
def test_owned_tunnel_closes_on_every_exit(monkeypatch, failure):
    process = owned_process(monkeypatch)
    if failure is None:
        with remote.ssh_tunnel("sensai-windows"):
            pass
    else:
        with pytest.raises(type(failure)) as caught:
            with remote.ssh_tunnel("sensai-windows"):
                raise failure
        assert caught.value is failure
    process.terminate.assert_called_once_with()
    process.wait.assert_called_once_with(timeout=3)
    process.kill.assert_not_called()


def test_ollama_missing_after_ssh_connect_is_an_error_and_closes_tunnel(monkeypatch):
    process = owned_process(monkeypatch)
    monkeypatch.setattr(remote, "_wait_for_ollama",
                        Mock(side_effect=remote.RemoteError("Ollama unavailable")))
    with pytest.raises(remote.RemoteError, match="Ollama"):
        with remote.ssh_tunnel("sensai-windows"):
            pytest.fail("CLI must not start")
    process.terminate.assert_called_once()


def test_system_ssh_argv_preserves_security_and_keeps_owned_foreground_process(monkeypatch):
    process = Mock()
    popen = Mock(return_value=process)
    monkeypatch.setattr(remote.subprocess, "Popen", popen)
    assert remote._start_tunnel("sensai-windows") is process
    command = popen.call_args.args[0]
    assert command[0:2] == ["ssh", "-NT"]
    assert command[-2:] == ["--", "sensai-windows"]
    assert command[command.index("-L") + 1] == "127.0.0.1:11435:127.0.0.1:11434"
    for option in ["ControlMaster=no", "ControlPath=none", "ControlPersist=no",
                   "ForkAfterAuthentication=no", "BatchMode=yes", "StrictHostKeyChecking=yes",
                   "ExitOnForwardFailure=yes", "ConnectTimeout=10", "ServerAliveInterval=30",
                   "ServerAliveCountMax=3"]:
        assert option in command
    assert not popen.call_args.kwargs.get("shell", False)
    assert popen.call_args.kwargs["start_new_session"] is True
    assert popen.call_args.kwargs["stdin"] == subprocess.DEVNULL


@pytest.mark.parametrize("failure", [FileNotFoundError("ssh"), PermissionError("ssh")])
def test_missing_or_unusable_ssh_is_clear_error(monkeypatch, failure):
    monkeypatch.setattr(remote.subprocess, "Popen", Mock(side_effect=failure))
    with pytest.raises(remote.RemoteError, match="cannot start OpenSSH"):
        remote._start_tunnel("sensai-windows")


def test_authentication_or_forwarding_failure_is_clear_error(monkeypatch):
    process = Mock()
    process.poll.return_value = 255
    with pytest.raises(remote.RemoteError, match="SSH failed"):
        remote._wait_for_ollama(process)


def test_startup_wait_is_bounded_and_never_yields_unavailable_ollama(monkeypatch):
    process = Mock()
    process.poll.return_value = None
    monkeypatch.setattr(remote, "ollama_running", lambda: False)
    ticks = iter([0, 1, 16, 17])
    monkeypatch.setattr(remote, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(remote, "sleep", lambda _: None)
    with pytest.raises(remote.RemoteError, match="Ollama"):
        remote._wait_for_ollama(process)


def test_cleanup_kills_only_owned_child_if_graceful_exit_times_out(monkeypatch):
    process = Mock()
    process.poll.return_value = None
    process.wait.side_effect = [subprocess.TimeoutExpired("ssh", 3), -9]
    remote._stop_tunnel(process)
    process.terminate.assert_called_once()
    process.kill.assert_called_once()
    assert [call.kwargs for call in process.wait.call_args_list] == [{"timeout": 3}, {"timeout": 3}]


@pytest.mark.parametrize("error", [OSError("cleanup failed"), subprocess.TimeoutExpired("ssh", 3)])
def test_cleanup_failure_preserves_chat_error(monkeypatch, error, capsys):
    process = owned_process(monkeypatch)
    process.terminate.side_effect = error
    process.kill.side_effect = error
    process.wait.side_effect = error
    original = ValueError("chat failed")
    with pytest.raises(ValueError) as caught:
        with remote.ssh_tunnel("sensai-windows"):
            raise original
    assert caught.value is original
    assert "warning:" in capsys.readouterr().err


def test_cleanup_failure_cannot_return_success(monkeypatch, capsys):
    configure(monkeypatch, alias="sensai-windows", host="http://127.0.0.1:11435")
    process = owned_process(monkeypatch)
    process.terminate.side_effect = OSError("cannot terminate")
    process.kill.side_effect = OSError("cannot kill")
    process.wait.side_effect = subprocess.TimeoutExpired("ssh", 3)
    monkeypatch.setattr(remote.cli, "run_chat", Mock())
    assert remote.main([]) == 1
    assert "error:" in capsys.readouterr().err


def test_launcher_errors_do_not_run_cli_or_fallback(monkeypatch, capsys):
    configure(monkeypatch, alias="sensai-windows", host="http://127.0.0.1:11435")
    monkeypatch.setattr(remote, "ollama_running", Mock(side_effect=remote.RemoteError("occupied")))
    monkeypatch.setattr(remote.cli, "run_chat", lambda *args: pytest.fail("CLI must not start"))
    assert remote.main([]) == 1
    assert "error: occupied" in capsys.readouterr().err


def test_interrupted_ssh_becomes_exit_130(monkeypatch):
    configure(monkeypatch, alias="sensai-windows", host="http://127.0.0.1:11435")
    monkeypatch.setattr(remote, "ollama_running", Mock(side_effect=KeyboardInterrupt()))
    assert remote.main([]) == 130


# --- Persona and session context prepared before the tunnel ---------------------------

@pytest.mark.parametrize("over_ssh", [False, True], ids=["local", "remote"])
def test_launcher_switches_with_context_loaded_once_before_tunnel(
    monkeypatch, tmp_path, capsys, over_ssh
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
        SENSAI_SSH_HOST="alias" if over_ssh else None,
        OLLAMA_HOST="http://127.0.0.1:11435" if over_ssh else "http://127.0.0.1:11434",
    )
    monkeypatch.setattr(remote, "Settings", lambda: settings)
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

    def create_client(client_settings, usage_sink=None):
        assert client_settings.host == settings.host
        assert events == (["tunnel opened"] if over_ssh else [])
        invalidate_loaded_files()
        events.append("client created")
        return client

    def forbidden(*args, **kwargs):
        pytest.fail("No real SSH or HTTP is allowed")

    monkeypatch.setattr(remote, "ssh_tunnel", tunnel)
    monkeypatch.setattr(remote, "HTTPConnection", forbidden)
    monkeypatch.setattr(remote.subprocess, "Popen", forbidden)
    monkeypatch.setattr(cli, "create_client", create_client)

    monkeypatch.setattr(cli, "TerminalInput", scripted_terminal(
        ["Draft", "/persona", "/persona Review Team", "Revise", "exit"]))
    assert remote.main([]) == 0
    assert events == (["tunnel opened", "client created", "tunnel closed"]
                      if over_ssh else ["client created"])
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


SESSION_PROFILE = "Profil de la créatrice (instructions personnalisées) :\n- ton : direct"


def configure_sessions(monkeypatch, tmp_path, over_ssh, events):
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Shared rules", encoding="utf-8")
    settings = Settings(
        _env_file=None, SENSAI_MODEL="fake-model", SENSAI_PROMPT=str(prompt),
        SENSAI_DB=str(tmp_path / "env.db"), SENSAI_CREATOR="env-creator",
        SENSAI_SSH_HOST="alias" if over_ssh else None,
        OLLAMA_HOST="http://127.0.0.1:11435" if over_ssh else "http://127.0.0.1:11434",
    )
    monkeypatch.setattr(remote, "Settings", lambda: settings)

    @contextmanager
    def tunnel(alias):
        events.append("tunnel opened")
        yield
        events.append("tunnel closed")

    monkeypatch.setattr(remote, "ssh_tunnel", tunnel)


@pytest.mark.usefixtures("isolated_settings")
@pytest.mark.parametrize("over_ssh", [False, True], ids=["local", "remote"])
def test_launcher_forwards_session_options(monkeypatch, tmp_path, capsys, over_ssh):
    events = []
    configure_sessions(monkeypatch, tmp_path, over_ssh, events)
    monkeypatch.setattr(saved_sessions, "new_session_id", lambda exists: "k7f2qa")
    profile = tmp_path / "profil.json"
    profile.write_text(json.dumps({"ton": "direct"}), encoding="utf-8")
    database = str(tmp_path / "cli.db")
    client = FakeClient(["R1"], ["R2"])

    def create_client(client_settings, usage_sink=None):
        events.append("client created")
        return client

    monkeypatch.setattr(cli, "create_client", create_client)
    monkeypatch.setattr(cli, "TerminalInput", scripted_terminal(["Q1", "exit"]))
    common = ["--db", database, "--creator", "alice"]
    assert remote.main([*common, "--profile-file", str(profile), "--persona", "analyse"]) == 0
    monkeypatch.setattr(cli, "TerminalInput", scripted_terminal(["Q2", "exit"]))
    assert remote.main([*common, "--session", "k7f2qa"]) == 0
    expected = ["tunnel opened", "client created", "tunnel closed"] if over_ssh else ["client created"]
    assert events == expected * 2
    system = "Shared rules\n\n" + SESSION_PROFILE + "\n\n" + PersonaRegistry.from_file().get(
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
        remote.main([*common, "--session", "zzzzzz"])
    assert remote.main([*common, "--list-sessions", "--host", "http://evil.example"]) == 0
    assert events == []
    assert capsys.readouterr().out.splitlines()[0].startswith("k7f2qa  ")
