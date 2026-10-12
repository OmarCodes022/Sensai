#!/usr/bin/env python3
"""Run the existing CLI with an optional, session-owned SSH tunnel."""

import json
import subprocess
import sys
from collections.abc import Sequence
from contextlib import contextmanager
from http.client import HTTPConnection, HTTPException
from pathlib import Path
from tempfile import TemporaryDirectory

from sensai.app import cli
from sensai.app.settings import Settings


class LauncherError(RuntimeError):
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
    raise LauncherError("port 11435 is occupied or unresponsive, but is not a valid Ollama endpoint")


def _start_master(alias: str, socket: Path) -> None:
    command = [
        "ssh", "-fNT", "-S", str(socket),
        "-o", "ControlMaster=yes", "-o", "ControlPersist=no",
        "-o", "StrictHostKeyChecking=yes", "-o", "ExitOnForwardFailure=yes",
        "-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=30",
        "-o", "ServerAliveCountMax=3",
        "-L", "127.0.0.1:11435:127.0.0.1:11434", "--", alias,
    ]
    try:
        process = subprocess.Popen(command)
    except OSError as error:
        raise LauncherError(f"cannot start OpenSSH: {error}") from error
    try:
        status = process.wait()
    except BaseException:
        for stop in (process.terminate, process.kill):
            try:
                stop()
            except (OSError, KeyboardInterrupt):
                pass
            try:
                process.wait(timeout=3)
                break
            except (OSError, subprocess.TimeoutExpired, KeyboardInterrupt):
                pass
        else:
            print("warning: could not reap the interrupted SSH process", file=sys.stderr)
        raise
    if status:
        raise LauncherError("SSH failed; check authentication, Tailscale access and availability of port 11435")


def _stop_master(alias: str, socket: Path) -> None:
    if not socket.exists():
        return
    try:
        result = subprocess.run(
            ["ssh", "-S", str(socket), "-O", "exit", "--", alias],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, timeout=3, check=False,
        )
        if result.returncode:
            print("warning: could not close the launcher SSH tunnel", file=sys.stderr)
    except (OSError, subprocess.TimeoutExpired, KeyboardInterrupt):
        print("warning: could not close the launcher SSH tunnel", file=sys.stderr)


@contextmanager
def ssh_tunnel(alias: str):
    if ollama_running():
        yield
        return
    # /tmp keeps the control socket below the Unix socket path limit on macOS.
    with TemporaryDirectory(prefix="sensai-", dir="/tmp") as directory:
        socket = Path(directory) / "ssh"
        try:
            _start_master(alias, socket)
            try:
                available = ollama_running()
            except LauncherError as error:
                raise LauncherError("SSH connected, but Ollama is unavailable on Windows port 11434") from error
            if not available:
                raise LauncherError("SSH connected, but Ollama is unavailable on Windows port 11434")
            yield
        finally:
            _stop_master(alias, socket)


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    settings = Settings()
    args = cli.parse_args(settings, argv)
    try:
        if args.list_personas or not settings.ssh_host:
            cli.main(argv)
            return 0
        alias = settings.ssh_host
        if alias.startswith("-") or not alias.isprintable() or any(c.isspace() for c in alias):
            raise LauncherError("SENSAI_SSH_HOST must be an SSH alias without whitespace, controls or leading '-'")
        if args.host not in ("http://127.0.0.1:11435", "http://127.0.0.1:11435/"):
            raise LauncherError("SENSAI_SSH_HOST requires OLLAMA_HOST/--host=http://127.0.0.1:11435")
        with ssh_tunnel(alias):
            cli.main(argv)
        return 0
    except LauncherError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
