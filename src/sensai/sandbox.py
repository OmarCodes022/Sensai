"""Run Python in a throw-away folder with time, CPU, memory and output limits.

This stops runaway or careless code, not deliberately malicious code: the child
can still use the network and read files by absolute path.
"""
from dataclasses import dataclass
import errno
import os
import resource
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
from time import monotonic, sleep

from sensai.core.cancellation import CancellationToken, OperationCancelled
from sensai.core.ports import ToolDefinition, ToolResult

PREFIX = "sensai-sandbox-"
_MB = 1024 * 1024
_PR_SET_PDEATHSIG = 1
_FILE_TOO_LARGE = f"[Errno {errno.EFBIG}] {os.strerror(errno.EFBIG)}"


class SandboxError(ValueError):
    """The run could not be prepared (data folder, temp folder or interpreter)."""


class _Terminated(BaseException):
    """SIGTERM arrived while the code was running."""


@dataclass(frozen=True)
class SandboxLimits:
    wall_seconds: float = 15.0
    cpu_seconds: int = 10
    memory_bytes: int = 512 * _MB
    file_bytes: int = 10 * _MB
    output_chars: int = 10_000
    data_bytes: int = 50 * _MB


@dataclass(frozen=True)
class SandboxRun:
    stdout: str
    stderr: str
    exit_code: int
    duration: float
    timed_out: bool
    truncated: bool


RUN_PYTHON = ToolDefinition(
    "run_python",
    "Run Python 3 code in a throw-away folder and return what it prints; "
    "data files are in the current folder.",
    {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]},
)


def _libc():
    if not sys.platform.startswith("linux"):
        return None
    try:
        import ctypes
        return ctypes.CDLL(None, use_errno=True)
    except (OSError, AttributeError):
        return None


def _lower(kind, soft, hard=None):
    hard = soft if hard is None else hard
    _, current = resource.getrlimit(kind)
    if current != resource.RLIM_INFINITY:
        hard = min(hard, current)
    resource.setrlimit(kind, (min(soft, hard), hard))


def _preexec(parent, libc, limits):
    """In the child, before exec: own process group, die with the parent, limits."""
    os.setpgid(0, 0)
    if libc is not None and libc.prctl(_PR_SET_PDEATHSIG, signal.SIGKILL, 0, 0, 0) == 0:
        if os.getppid() != parent:
            os._exit(1)
    _lower(resource.RLIMIT_CPU, limits.cpu_seconds, limits.cpu_seconds + 1)
    try:
        _lower(resource.RLIMIT_AS, limits.memory_bytes)
    except (ValueError, OSError):
        pass  # macOS does not support an address-space limit.
    _lower(resource.RLIMIT_FSIZE, limits.file_bytes)
    _lower(resource.RLIMIT_CORE, 0)


def _dead(owner):
    """True only for a usable pid that no longer exists."""
    try:
        os.kill(int(owner), 0)
    except ProcessLookupError:
        return True
    except (PermissionError, ValueError, OverflowError):
        return False
    return False


def remove_stale_folders() -> None:
    """Remove our sandbox folders left behind by processes that no longer exist."""
    try:
        entries = os.scandir(tempfile.gettempdir())
    except OSError:
        return
    with entries:
        for entry in entries:
            owner = entry.name[len(PREFIX):].split("-", 1)[0]
            if not entry.name.startswith(PREFIX) or not (owner.isascii() and owner.isdigit()):
                continue
            try:
                if (not entry.is_dir(follow_symlinks=False)
                        or entry.stat(follow_symlinks=False).st_uid != os.getuid()):
                    continue
            except OSError:
                continue
            if _dead(owner):
                shutil.rmtree(entry.path, ignore_errors=True)


def _data_files(data_dir, limit):
    """Top-level regular files of data_dir, sorted, with their total size checked."""
    if data_dir is None:
        return []
    path = os.fspath(data_dir)
    if not os.path.isdir(path):
        raise SandboxError(f"data folder not found: {path}")
    try:
        with os.scandir(path) as entries:
            files = sorted((e for e in entries if e.is_file(follow_symlinks=False)),
                           key=lambda e: e.name)
            total = sum(e.stat(follow_symlinks=False).st_size for e in files)
    except OSError as exc:
        raise SandboxError(f"cannot read data folder: {exc}") from exc
    if total > limit:
        raise SandboxError(f"data folder is larger than {limit / _MB:g} MB")
    return [(e.path, e.name) for e in files]


def _copy_data(files, target, limit):
    budget = limit
    for source, name in files:
        flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(source, flags)
        except OSError:
            continue  # Replaced by a symlink or removed since the listing.
        with open(fd, "rb") as src:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                continue
            with open(os.path.join(target, name), "xb") as dst:
                while chunk := src.read(min(1024 * 1024, budget + 1)):
                    budget -= len(chunk)
                    if budget < 0:
                        raise SandboxError(f"data folder is larger than {limit / _MB:g} MB")
                    dst.write(chunk)


def _exited(process):
    """Exit check that leaves the zombie in place, so its process group id stays ours."""
    if hasattr(os, "waitid"):
        return os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None
    return process.poll() is not None


def _kill(process):
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass  # The group is already gone (macOS may report an exited group as EPERM).
    try:
        process.kill()  # Code that moved to another group; its pid is not reaped yet.
    except ProcessLookupError:
        pass
    process.wait()


class _TermGuard:
    """While active in the main thread, SIGTERM is recorded and raised at check()."""

    def __init__(self):
        self.terminated = False
        self.previous = None

    def __enter__(self):
        if threading.current_thread() is not threading.main_thread():
            return self
        previous = signal.getsignal(signal.SIGTERM)
        if previous is None or previous is signal.SIG_IGN:
            return self
        try:
            signal.signal(signal.SIGTERM, self._record)
        except ValueError:
            return self
        self.previous = previous
        return self

    def _record(self, signum, frame):
        self.terminated = True

    def check(self):
        if self.terminated:
            raise _Terminated()

    def __exit__(self, *exc):
        if self.previous is not None:
            signal.signal(signal.SIGTERM, self.previous)
        if self.terminated:
            # Clean-up is done: let the original disposition handle the signal.
            signal.raise_signal(signal.SIGTERM)
            raise OperationCancelled("sandbox stopped by SIGTERM")
        return False


class _Output:
    """Bounded head of stdout and rolling tail of stderr; the excess is drained."""

    def __init__(self, cap):
        self.cap = cap
        self.out = bytearray()
        self.err = bytearray()
        self.cut = False

    def add(self, name, data):
        if name == "out":
            keep = self.cap - len(self.out)
            self.out += data[:max(keep, 0)]
            self.cut = self.cut or len(data) > keep
        else:
            self.err += data
            if len(self.err) > self.cap:
                del self.err[:-self.cap]
                self.cut = True


def _collect(process, limits, token, guard):
    output = _Output(4 * limits.output_chars)
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, "out")
    selector.register(process.stderr, selectors.EVENT_READ, "err")
    deadline = monotonic() + limits.wall_seconds
    timed_out = False
    try:
        while True:
            guard.check()
            if token is not None:
                token.raise_if_cancelled()
            exited = _exited(process)
            remaining = deadline - monotonic()
            if remaining <= 0:
                timed_out = not exited
                break
            if not selector.get_map():
                if exited:
                    break
                sleep(min(.02, remaining))
                continue
            ready = selector.select(0 if exited else min(.02, remaining))
            if exited and not ready:
                break
            for key, _ in ready:
                data = os.read(key.fd, 65536)
                if data:
                    output.add(key.data, data)
                else:
                    selector.unregister(key.fileobj)
    finally:
        selector.close()
    return output, timed_out


def _text(data, limit, tail, folder):
    text = data.decode("utf-8", errors="replace").replace(folder + os.sep, "").replace(folder, ".")
    if len(text) <= limit:
        return text, False
    return (text[-limit:] if tail else text[:limit]), True


def run_python(code: str, data_dir: str | os.PathLike | None = None,
               cancellation: CancellationToken | None = None, *,
               limits: SandboxLimits = SandboxLimits()) -> SandboxRun:
    """Run code as main.py in a new temp folder; the folder never outlives the call."""
    if cancellation is not None:
        cancellation.raise_if_cancelled()
    remove_stale_folders()
    files = _data_files(data_dir, limits.data_bytes)
    libc = _libc()
    with _TermGuard() as guard:
        folder = process = None
        try:
            try:
                folder = os.path.realpath(tempfile.mkdtemp(prefix=f"{PREFIX}{os.getpid()}-"))
                _copy_data(files, folder, limits.data_bytes)
                # A BOM makes CPython reject any other coding cookie (utf-7, unicode_escape…),
                # so the code runs exactly as the approval preview showed it.
                with open(os.path.join(folder, "main.py"), "w", encoding="utf-8-sig") as script:
                    script.write(code[1:] if code.startswith("\ufeff") else code)
            except OSError as exc:
                raise SandboxError(f"cannot prepare the sandbox folder: {exc.strerror or exc}") from exc
            guard.check()
            env = {"PATH": os.defpath, "LANG": "C.UTF-8", "PYTHONIOENCODING": "utf-8",
                   "PYTHONDONTWRITEBYTECODE": "1", "HOME": folder, "TMPDIR": folder}
            parent = os.getpid()
            started = monotonic()
            try:
                process = subprocess.Popen(
                    [sys.executable, "-I", "main.py"], cwd=folder, env=env,
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    close_fds=True, preexec_fn=lambda: _preexec(parent, libc, limits))
            except (OSError, subprocess.SubprocessError) as exc:
                raise SandboxError(f"cannot start Python: {exc}") from exc
            output, timed_out = _collect(process, limits, cancellation, guard)
            duration = monotonic() - started
        finally:
            try:
                if process is not None:
                    try:
                        _kill(process)
                    finally:
                        process.stdout.close()
                        process.stderr.close()
            finally:
                if folder is not None:
                    shutil.rmtree(folder, ignore_errors=True)
    timed_out = timed_out and process.returncode < 0
    stdout, cut_out = _text(output.out, limits.output_chars, False, folder)
    stderr, cut_err = _text(output.err, limits.output_chars, True, folder)
    return SandboxRun(stdout, stderr, process.returncode, duration, timed_out,
                      output.cut or cut_out or cut_err)


def format_run(run: SandboxRun, limits: SandboxLimits = SandboxLimits()) -> str:
    lines = [f"Exit code {run.exit_code} · {run.duration:.1f} s"]
    if run.timed_out:
        lines.append(f"Time limit reached ({limits.wall_seconds:g} s)")
    elif run.exit_code == -signal.SIGXCPU:
        lines.append("CPU time limit reached")
    elif run.exit_code == -signal.SIGXFSZ or run.exit_code and _FILE_TOO_LARGE in run.stderr:
        lines.append(f"File size limit reached ({limits.file_bytes / _MB:g} MB)")
    elif run.exit_code < 0:
        try:
            name = signal.Signals(-run.exit_code).name
        except ValueError:
            name = str(-run.exit_code)
        lines.append(f"Killed by signal {name}")
    if run.truncated:
        lines.append("(output truncated)")
    for label, text in (("stdout", run.stdout), ("stderr", run.stderr)):
        if text:
            lines += [f"{label}:", text.rstrip("\n")]
    return "\n".join(lines)


def python_tool(arguments, cancellation=None, *, data_dir=None) -> ToolResult:
    try:
        run = run_python(arguments["code"], data_dir, cancellation)
    except SandboxError as exc:
        return ToolResult("", str(exc))
    text = format_run(run)
    return ToolResult(text, text if run.exit_code != 0 or run.timed_out else None)
