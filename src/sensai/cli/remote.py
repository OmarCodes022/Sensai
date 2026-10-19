"""Run the CLI with an optional, session-owned SSH tunnel to a remote Ollama (`sensai-remote`)."""

import json
import signal
import subprocess
import sys
from collections.abc import Sequence
from contextlib import contextmanager
from http.client import HTTPConnection, HTTPException
from time import monotonic, sleep

from sensai.cli import main as cli
from sensai.settings import Settings


class RemoteError(RuntimeError):
    """The configured remote Ollama connection could not be established."""


def ollama_running() -> bool:
    """Probe only loopback, without HTTP proxies or redirects."""
    connection = HTTPConnection("127.0.0.1", 11435, timeout=2)
    try:
        try:
            connection.connect()
        except ConnectionRefusedError:
            return False
        connection.request("GET", "/api/tags")
        response = connection.getresponse()
        body = response.read(1024 * 1024 + 1)
        if response.status == 200 and len(body) <= 1024 * 1024:
            data = json.loads(body)
            if isinstance(data, dict) and isinstance(data.get("models"), list):
                return True
    except (OSError, HTTPException, ValueError, RecursionError):
        pass
    finally:
        connection.close()
    raise RemoteError("port 11435 is occupied or unresponsive, but is not a valid Ollama endpoint")


class RemoteSignal(BaseException):
    def __init__(self, signum: int):
        self.signum = signum


def _start_tunnel(alias: str) -> subprocess.Popen:
    command = [
        "ssh", "-NT",
        "-o", "ControlMaster=no", "-o", "ControlPath=none", "-o", "ControlPersist=no",
        "-o", "ForkAfterAuthentication=no", "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=yes", "-o", "ExitOnForwardFailure=yes",
        "-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=30",
        "-o", "ServerAliveCountMax=3",
        "-L", "127.0.0.1:11435:127.0.0.1:11434", "--", alias,
    ]
    try:
        return subprocess.Popen(command, stdin=subprocess.DEVNULL, start_new_session=True)
    except OSError as error:
        raise RemoteError(f"cannot start OpenSSH: {error}") from error


def _wait_for_ollama(process: subprocess.Popen) -> None:
    deadline = monotonic() + 15
    while monotonic() < deadline:
        if process.poll() is not None:
            raise RemoteError("SSH failed; unlock your key with ssh-add and check authentication, "
                                "Tailscale access and availability of port 11435")
        try:
            if ollama_running():
                if process.poll() is not None:
                    raise RemoteError("SSH exited while opening the tunnel")
                return
        except RemoteError as error:
            raise RemoteError("SSH started, but Ollama is unavailable on Windows port 11434 "
                                "or port 11435 is occupied by an invalid endpoint") from error
        sleep(.1)
    raise RemoteError("SSH/Ollama startup timed out; check Windows Ollama on port 11434 "
                        "and unlock your key with ssh-add")


def _stop_tunnel(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        process.wait(timeout=3)
        return
    for stop in (process.terminate, process.kill):
        try:
            stop()
        except ProcessLookupError:
            pass
        except OSError:
            # Still try to reap it, then escalate to kill if necessary.
            pass
        try:
            process.wait(timeout=3)
            return
        except (OSError, subprocess.TimeoutExpired):
            pass
    raise RemoteError(f"could not terminate/reap the launcher SSH process (PID {process.pid})")


@contextmanager
def ssh_tunnel(alias: str):
    if ollama_running():
        yield
        return
    process = None
    spawning = True
    pending_signal = None
    original = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT)}

    def interrupted(signum, frame):
        nonlocal pending_signal
        if spawning:
            # Defer until the child handle is owned, so an interrupted Popen cannot orphan it.
            pending_signal = signum
        else:
            raise RemoteSignal(signum)

    try:
        for sig in original:
            signal.signal(sig, interrupted)
        process = _start_tunnel(alias)
        spawning = False
        signal.signal(signal.SIGINT, original[signal.SIGINT])
        if pending_signal is not None:
            if pending_signal == signal.SIGINT:
                raise KeyboardInterrupt
            raise RemoteSignal(pending_signal)
        _wait_for_ollama(process)
        yield
        if process.poll() is not None:
            raise RemoteError("SSH tunnel exited during chat; launch again to reconnect")
    finally:
        active_error = sys.exc_info()[1]
        try:
            # Cleanup is bounded and must survive a second interrupt or hangup.
            previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, original)
            try:
                for sig in original:
                    signal.signal(sig, signal.SIG_IGN)
            finally:
                signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
            if process is not None:
                try:
                    _stop_tunnel(process)
                except (RemoteError, OSError, subprocess.TimeoutExpired) as error:
                    if active_error is None:
                        raise RemoteError(str(error)) from error
                    print(f"warning: SSH cleanup failed: {error}", file=sys.stderr)
        finally:
            for sig, handler in original.items():
                signal.signal(sig, handler)


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    settings = Settings()
    args = cli.parse_args(settings, argv)
    try:
        prepared = cli.prepare_chat(args)
        if prepared is None:
            return 0
        if not settings.ssh_host:
            cli.run_chat(settings, args, prepared)
            return 0
        alias = settings.ssh_host
        if alias.startswith("-") or not alias.isprintable() or any(c.isspace() for c in alias):
            raise RemoteError("SENSAI_SSH_HOST must be an SSH alias without whitespace, controls or leading '-'")
        if args.host not in ("http://127.0.0.1:11435", "http://127.0.0.1:11435/"):
            raise RemoteError("SENSAI_SSH_HOST requires OLLAMA_HOST/--host=http://127.0.0.1:11435")
        with ssh_tunnel(alias):
            cli.run_chat(settings, args, prepared)
        return 0
    except RemoteError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except RemoteSignal as error:
        return 128 + error.signum
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
