"""Launcher contracts without contacting Ollama or starting real SSH processes."""
import importlib.util
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from sensai.app.settings import Settings


SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "run_sensai.py"
spec = importlib.util.spec_from_file_location("run_sensai", SCRIPT)
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


@pytest.fixture(autouse=True)
def no_external_io(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Tests must not contact HTTP or run real SSH")

    monkeypatch.setattr(launcher, "HTTPConnection", forbidden)
    monkeypatch.setattr(launcher.subprocess, "Popen", forbidden)
    monkeypatch.setattr(launcher.subprocess, "run", forbidden)


def configure(monkeypatch, *, alias=None, host="http://127.0.0.1:11434"):
    settings = Settings(_env_file=None, SENSAI_MODEL="configured-model",
                        SENSAI_SSH_HOST=alias, OLLAMA_HOST=host,
                        SENSAI_PROMPT=str(SCRIPT.parent.parent / "prompts/system.txt"))
    monkeypatch.setattr(launcher, "Settings", lambda: settings)
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
    monkeypatch.setattr(launcher, "ollama_running", probe)
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
        launcher.main(args)
    probe.assert_not_called()


@pytest.mark.parametrize("alias", [None, ""])
def test_local_launch_does_not_probe_or_start_ssh(monkeypatch, alias):
    configure(monkeypatch, alias=alias)
    run = Mock()
    monkeypatch.setattr(launcher.cli, "run_chat", run)
    args = ["selected-model", "--persona", "redaction"]
    assert launcher.main(args) == 0
    run.assert_called_once()
    assert run.call_args.args[1].model == args[0]
    assert run.call_args.args[2]


def test_help_never_connects_even_with_bad_remote_configuration(monkeypatch, capsys):
    configure(monkeypatch, alias="-invalid", host="https://remote.example")
    with pytest.raises(SystemExit) as result:
        launcher.main(["--help"])
    assert result.value.code == 0
    assert "--persona" in capsys.readouterr().out


def test_list_personas_needs_no_model_or_connection(monkeypatch, capsys):
    settings = Settings(_env_file=None, SENSAI_MODEL=None, SENSAI_SSH_HOST="-invalid",
                        OLLAMA_HOST="https://remote.example", SENSAI_PERSONAS_FILE=None)
    monkeypatch.setattr(launcher, "Settings", lambda: settings)
    assert launcher.main(["--list-personas"]) == 0
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

    monkeypatch.setattr(launcher, "ssh_tunnel", tunnel)
    run = Mock()
    monkeypatch.setattr(launcher.cli, "run_chat", run)
    args = ["cli-model", "--host", host, "--persona", "analyse"]
    assert launcher.main(args) == 0
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
    monkeypatch.setattr(launcher.cli, "run_chat", lambda *args: pytest.fail("CLI was run"))
    assert launcher.main(["--host", host]) == 1
    assert "requires OLLAMA_HOST/--host" in capsys.readouterr().err


@pytest.mark.parametrize("alias", ["-oProxyCommand=bad", "two words", "alias\nother", "alias\x00", "\t"])
def test_invalid_ssh_alias_fails_before_network(monkeypatch, capsys, alias):
    configure(monkeypatch, alias=alias, host="http://127.0.0.1:11435")
    monkeypatch.setattr(launcher.cli, "run_chat", lambda *args: pytest.fail("CLI was run"))
    assert launcher.main([]) == 1
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
    args = launcher.cli.parse_args(settings, ["cli-model", "--host", "http://127.0.0.1:11435"])
    assert (args.model, args.host) == ("cli-model", "http://127.0.0.1:11435")
    monkeypatch.setenv("SENSAI_SSH_HOST", "")
    assert not Settings().ssh_host


def http_connection(monkeypatch, *, status=200, body=b'{"models": []}'):
    connection = Mock()
    response = connection.getresponse.return_value
    response.status = status
    response.read.return_value = body
    constructor = Mock(return_value=connection)
    monkeypatch.setattr(launcher, "HTTPConnection", constructor)
    return constructor, connection


def test_probe_uses_only_bounded_loopback_http(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://must-not-be-used.example")
    constructor, connection = http_connection(monkeypatch)
    assert launcher.ollama_running() is True
    constructor.assert_called_once_with("127.0.0.1", 11435, timeout=2)
    connection.request.assert_called_once_with("GET", "/api/tags")
    connection.getresponse.return_value.read.assert_called_once_with(1024 * 1024 + 1)
    connection.close.assert_called_once_with()


def test_only_connection_refusal_means_no_existing_tunnel(monkeypatch):
    _, connection = http_connection(monkeypatch)
    connection.connect.side_effect = ConnectionRefusedError()
    assert launcher.ollama_running() is False
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
    with pytest.raises(launcher.LauncherError, match="port 11435"):
        launcher.ollama_running()
    connection.close.assert_called_once_with()


@pytest.mark.parametrize("error", [TimeoutError(), ConnectionResetError(), OSError("failure")])
def test_probe_failure_cannot_trigger_an_ssh_fallback(monkeypatch, error):
    _, connection = http_connection(monkeypatch)
    connection.connect.side_effect = error
    with pytest.raises(launcher.LauncherError):
        launcher.ollama_running()
    connection.close.assert_called_once_with()


def test_preexisting_tunnel_is_never_closed(monkeypatch):
    monkeypatch.setattr(launcher, "ollama_running", lambda: True)
    monkeypatch.setattr(launcher, "_stop_tunnel", lambda *args: pytest.fail("Existing tunnel closed"))
    with launcher.ssh_tunnel("sensai-windows"):
        pass


def owned_process(monkeypatch):
    process = Mock()
    process.poll.return_value = None
    process.wait.return_value = 0
    monkeypatch.setattr(launcher, "ollama_running", lambda: False)
    monkeypatch.setattr(launcher, "_start_tunnel", lambda _: process)
    monkeypatch.setattr(launcher, "_wait_for_ollama", lambda _: None)
    return process


@pytest.mark.parametrize("failure", [None, RuntimeError("chat failed"), KeyboardInterrupt()])
def test_owned_tunnel_closes_on_every_exit(monkeypatch, failure):
    process = owned_process(monkeypatch)
    if failure is None:
        with launcher.ssh_tunnel("sensai-windows"):
            pass
    else:
        with pytest.raises(type(failure)) as caught:
            with launcher.ssh_tunnel("sensai-windows"):
                raise failure
        assert caught.value is failure
    process.terminate.assert_called_once_with()
    process.wait.assert_called_once_with(timeout=3)
    process.kill.assert_not_called()


def test_ollama_missing_after_ssh_connect_is_an_error_and_closes_tunnel(monkeypatch):
    process = owned_process(monkeypatch)
    monkeypatch.setattr(launcher, "_wait_for_ollama",
                        Mock(side_effect=launcher.LauncherError("Ollama unavailable")))
    with pytest.raises(launcher.LauncherError, match="Ollama"):
        with launcher.ssh_tunnel("sensai-windows"):
            pytest.fail("CLI must not start")
    process.terminate.assert_called_once()


def test_system_ssh_argv_preserves_security_and_keeps_owned_foreground_process(monkeypatch):
    process = Mock()
    popen = Mock(return_value=process)
    monkeypatch.setattr(launcher.subprocess, "Popen", popen)
    assert launcher._start_tunnel("sensai-windows") is process
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
    monkeypatch.setattr(launcher.subprocess, "Popen", Mock(side_effect=failure))
    with pytest.raises(launcher.LauncherError, match="cannot start OpenSSH"):
        launcher._start_tunnel("sensai-windows")


def test_authentication_or_forwarding_failure_is_clear_error(monkeypatch):
    process = Mock()
    process.poll.return_value = 255
    with pytest.raises(launcher.LauncherError, match="SSH failed"):
        launcher._wait_for_ollama(process)


def test_startup_wait_is_bounded_and_never_yields_unavailable_ollama(monkeypatch):
    process = Mock()
    process.poll.return_value = None
    monkeypatch.setattr(launcher, "ollama_running", lambda: False)
    ticks = iter([0, 1, 16, 17])
    monkeypatch.setattr(launcher, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(launcher, "sleep", lambda _: None)
    with pytest.raises(launcher.LauncherError, match="Ollama"):
        launcher._wait_for_ollama(process)


def test_cleanup_kills_only_owned_child_if_graceful_exit_times_out(monkeypatch):
    process = Mock()
    process.poll.return_value = None
    process.wait.side_effect = [subprocess.TimeoutExpired("ssh", 3), -9]
    launcher._stop_tunnel(process)
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
        with launcher.ssh_tunnel("sensai-windows"):
            raise original
    assert caught.value is original
    assert "warning:" in capsys.readouterr().err


def test_cleanup_failure_cannot_return_success(monkeypatch, capsys):
    configure(monkeypatch, alias="sensai-windows", host="http://127.0.0.1:11435")
    process = owned_process(monkeypatch)
    process.terminate.side_effect = OSError("cannot terminate")
    process.kill.side_effect = OSError("cannot kill")
    process.wait.side_effect = subprocess.TimeoutExpired("ssh", 3)
    monkeypatch.setattr(launcher.cli, "run_chat", Mock())
    assert launcher.main([]) == 1
    assert "error:" in capsys.readouterr().err


def test_launcher_errors_do_not_run_cli_or_fallback(monkeypatch, capsys):
    configure(monkeypatch, alias="sensai-windows", host="http://127.0.0.1:11435")
    monkeypatch.setattr(launcher, "ollama_running", Mock(side_effect=launcher.LauncherError("occupied")))
    monkeypatch.setattr(launcher.cli, "run_chat", lambda *args: pytest.fail("CLI must not start"))
    assert launcher.main([]) == 1
    assert "error: occupied" in capsys.readouterr().err


def test_interrupted_ssh_becomes_exit_130(monkeypatch):
    configure(monkeypatch, alias="sensai-windows", host="http://127.0.0.1:11435")
    monkeypatch.setattr(launcher, "ollama_running", Mock(side_effect=KeyboardInterrupt()))
    assert launcher.main([]) == 130
