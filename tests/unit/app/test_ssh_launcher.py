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
                        SENSAI_SSH_HOST=alias, OLLAMA_HOST=host)
    monkeypatch.setattr(launcher, "Settings", lambda: settings)
    return settings


@pytest.mark.parametrize("alias", [None, ""])
def test_local_launch_does_not_probe_or_start_ssh(monkeypatch, alias):
    configure(monkeypatch, alias=alias)
    run = Mock()
    monkeypatch.setattr(launcher.cli, "main", run)
    args = ["selected-model", "--persona", "redaction"]
    assert launcher.main(args) == 0
    run.assert_called_once_with(args)


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
    monkeypatch.setattr(launcher.cli, "main", run)
    args = ["cli-model", "--host", host, "--persona", "analyse"]
    assert launcher.main(args) == 0
    assert seen == ["sensai-windows"]
    run.assert_called_once_with(args)


@pytest.mark.parametrize("host", [
    "http://localhost:11435", "http://127.0.0.1:11434", "https://127.0.0.1:11435",
    "http://127.0.0.1:11435/path", "http://user@127.0.0.1:11435", "http://evil.example",
])
def test_remote_host_must_be_exact_loopback_endpoint(monkeypatch, capsys, host):
    configure(monkeypatch, alias="sensai-windows", host="http://127.0.0.1:11435")
    monkeypatch.setattr(launcher.cli, "main", lambda _: pytest.fail("CLI was run"))
    assert launcher.main(["--host", host]) == 1
    assert "requires OLLAMA_HOST/--host" in capsys.readouterr().err


@pytest.mark.parametrize("alias", ["-oProxyCommand=bad", "two words", "alias\nother", "alias\x00", "\t"])
def test_invalid_ssh_alias_fails_before_network(monkeypatch, capsys, alias):
    configure(monkeypatch, alias=alias, host="http://127.0.0.1:11435")
    monkeypatch.setattr(launcher.cli, "main", lambda _: pytest.fail("CLI was run"))
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
    monkeypatch.setattr(launcher, "_stop_master", lambda *args: pytest.fail("Existing tunnel closed"))
    with launcher.ssh_tunnel("sensai-windows"):
        pass


@pytest.mark.parametrize("failure", [None, RuntimeError("chat failed"), KeyboardInterrupt()])
def test_owned_tunnel_uses_private_unique_socket_and_closes_on_every_exit(monkeypatch, failure):
    probes = iter([False, True, False, True])
    monkeypatch.setattr(launcher, "ollama_running", lambda: next(probes))
    starts, stops = [], []

    def start(alias, socket):
        assert socket.parent.stat().st_mode & 0o777 == 0o700
        assert len(str(socket).encode()) < 104
        starts.append((alias, socket))

    monkeypatch.setattr(launcher, "_start_master", start)
    monkeypatch.setattr(launcher, "_stop_master", lambda *args: stops.append(args))
    for _ in range(2):
        if failure is None:
            with launcher.ssh_tunnel("sensai-windows"):
                pass
        else:
            with pytest.raises(type(failure)) as caught:
                with launcher.ssh_tunnel("sensai-windows"):
                    raise failure
            assert caught.value is failure
    assert starts == stops
    assert starts[0][1] != starts[1][1]
    assert not starts[0][1].parent.exists()


@pytest.mark.parametrize("failure", [launcher.LauncherError("auth failed"), KeyboardInterrupt()])
def test_failed_or_interrupted_start_cleans_only_owned_master(monkeypatch, failure):
    monkeypatch.setattr(launcher, "ollama_running", lambda: False)
    paths = []

    def start(alias, socket):
        paths.append((alias, socket))
        raise failure

    stopped = Mock()
    monkeypatch.setattr(launcher, "_start_master", start)
    monkeypatch.setattr(launcher, "_stop_master", stopped)
    with pytest.raises(type(failure)) as caught:
        with launcher.ssh_tunnel("sensai-windows"):
            pytest.fail("Failed tunnel was yielded")
    assert caught.value is failure
    stopped.assert_called_once_with(*paths[0])


def test_ollama_missing_after_ssh_connect_is_an_error_and_closes_tunnel(monkeypatch):
    monkeypatch.setattr(launcher, "ollama_running", lambda: False)
    monkeypatch.setattr(launcher, "_start_master", lambda *args: None)
    stop = Mock()
    monkeypatch.setattr(launcher, "_stop_master", stop)
    with pytest.raises(launcher.LauncherError, match="Ollama.*Windows port 11434"):
        with launcher.ssh_tunnel("sensai-windows"):
            pytest.fail("CLI must not start")
    stop.assert_called_once()


def test_system_ssh_argv_preserves_security_and_interactive_stdio(monkeypatch, tmp_path):
    process = Mock()
    process.wait.return_value = 0
    popen = Mock(return_value=process)
    monkeypatch.setattr(launcher.subprocess, "Popen", popen)
    socket = tmp_path / "ssh"
    launcher._start_master("sensai-windows", socket)
    command = popen.call_args.args[0]
    assert command[0:2] == ["ssh", "-fNT"]
    assert command[-2:] == ["--", "sensai-windows"]
    assert command[command.index("-S") + 1] == str(socket)
    assert command[command.index("-L") + 1] == "127.0.0.1:11435:127.0.0.1:11434"
    for option in ["ControlMaster=yes", "ControlPersist=no", "StrictHostKeyChecking=yes",
                   "ExitOnForwardFailure=yes", "ConnectTimeout=10", "ServerAliveInterval=30",
                   "ServerAliveCountMax=3"]:
        assert option in command
    assert not popen.call_args.kwargs.get("shell", False)
    for name in ("stdin", "stdout", "stderr"):
        assert popen.call_args.kwargs.get(name) is None


@pytest.mark.parametrize("failure", [FileNotFoundError("ssh"), PermissionError("ssh")])
def test_missing_or_unusable_ssh_is_clear_error(monkeypatch, tmp_path, failure):
    monkeypatch.setattr(launcher.subprocess, "Popen", Mock(side_effect=failure))
    with pytest.raises(launcher.LauncherError, match="cannot start OpenSSH"):
        launcher._start_master("sensai-windows", tmp_path / "ssh")


def test_authentication_or_forwarding_failure_is_clear_error(monkeypatch, tmp_path):
    process = Mock()
    process.wait.return_value = 255
    monkeypatch.setattr(launcher.subprocess, "Popen", Mock(return_value=process))
    with pytest.raises(launcher.LauncherError, match="SSH failed"):
        launcher._start_master("sensai-windows", tmp_path / "ssh")


def test_interrupted_start_terminates_child_and_bounds_cleanup(monkeypatch, tmp_path):
    process = Mock()
    interrupted = KeyboardInterrupt()
    process.wait.side_effect = [interrupted, subprocess.TimeoutExpired("ssh", 3), 0]
    monkeypatch.setattr(launcher.subprocess, "Popen", Mock(return_value=process))
    with pytest.raises(KeyboardInterrupt) as caught:
        launcher._start_master("sensai-windows", tmp_path / "ssh")
    assert caught.value is interrupted
    process.terminate.assert_called_once()
    process.kill.assert_called_once()
    assert all(call.kwargs == {"timeout": 3} for call in process.wait.call_args_list[1:])


@pytest.mark.parametrize("error", [OSError("cleanup failed"), subprocess.TimeoutExpired("ssh", 3), KeyboardInterrupt()])
def test_cleanup_failure_preserves_chat_error(monkeypatch, tmp_path, error, capsys):
    monkeypatch.setattr(launcher, "ollama_running", Mock(side_effect=[False, True]))
    monkeypatch.setattr(launcher, "_start_master", lambda alias, socket: socket.touch())
    stop = Mock(side_effect=error)
    monkeypatch.setattr(launcher.subprocess, "run", stop)
    original = ValueError("chat failed")
    with pytest.raises(ValueError) as caught:
        with launcher.ssh_tunnel("sensai-windows"):
            raise original
    assert caught.value is original
    assert stop.call_args.kwargs["timeout"] == 3
    assert "warning:" in capsys.readouterr().err


def test_cleanup_never_uses_a_global_process_kill(monkeypatch, tmp_path):
    socket = tmp_path / "ssh"
    socket.touch()
    run = Mock(return_value=Mock(returncode=0))
    monkeypatch.setattr(launcher.subprocess, "run", run)
    launcher._stop_master("sensai-windows", socket)
    assert run.call_args.args[0] == ["ssh", "-S", str(socket), "-O", "exit", "--", "sensai-windows"]
    assert run.call_args.kwargs["timeout"] == 3


def test_launcher_errors_do_not_run_cli_or_fallback(monkeypatch, capsys):
    configure(monkeypatch, alias="sensai-windows", host="http://127.0.0.1:11435")
    monkeypatch.setattr(launcher, "ollama_running", Mock(side_effect=launcher.LauncherError("occupied")))
    monkeypatch.setattr(launcher.cli, "main", lambda _: pytest.fail("CLI must not start"))
    assert launcher.main([]) == 1
    assert "error: occupied" in capsys.readouterr().err


def test_interrupted_ssh_becomes_exit_130(monkeypatch):
    configure(monkeypatch, alias="sensai-windows", host="http://127.0.0.1:11435")
    monkeypatch.setattr(launcher, "ollama_running", Mock(side_effect=KeyboardInterrupt()))
    assert launcher.main([]) == 130


@pytest.mark.parametrize("cleanup_error", [PermissionError("cannot signal child"), KeyboardInterrupt()])
def test_interrupted_start_preserves_original_exception_if_cleanup_fails(monkeypatch, tmp_path, cleanup_error):
    process = Mock()
    interrupted = KeyboardInterrupt()
    process.wait.side_effect = [interrupted, 0]
    process.terminate.side_effect = cleanup_error
    monkeypatch.setattr(launcher.subprocess, "Popen", Mock(return_value=process))
    with pytest.raises(KeyboardInterrupt) as caught:
        launcher._start_master("sensai-windows", tmp_path / "ssh")
    assert caught.value is interrupted
