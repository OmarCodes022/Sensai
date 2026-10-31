"""Run Python in a throw-away folder with time, CPU, memory and output limits.

This stops runaway or careless code, not deliberately malicious code: the child
can still use the network and read files by absolute path.
"""
from dataclasses import dataclass
import errno
import os
import re
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
from sensai.core.ports import PermissionPort, PermissionRequest, ToolDefinition, ToolResult

PREFIX = "sensai-sandbox-"
_MB = 1024 * 1024
_PR_SET_PDEATHSIG = 1
_FILE_TOO_LARGE = f"[Errno {errno.EFBIG}] {os.strerror(errno.EFBIG)}"
# Exactly what mkdtemp(prefix=f"{PREFIX}{pid}-") creates: 8 characters from its alphabet.
_OURS = re.compile(re.escape(PREFIX) + r"([0-9]+)-[a-z0-9_]{8}")
# Data files Python could import instead of the standard library (3.10 has no -P).
_IMPORTABLE = (".py", ".pyc", ".pyw", ".so", ".pyd")
_DRAIN_SECONDS = .2
PYTHON_ATTEMPTS = 3  # run_python calls per question, in the CLI and the web chat.
MODEL_CHARS = 2000
FIX_IT = "If it failed, fix the code and call run_python again; otherwise answer using this output."
_NOT_ALLOWED = "Not available (not allowed): "
_STATUS = re.compile(r"Exit code (-?[0-9]+) · ")
_LABEL = re.compile(r"(stdout|stderr)(?: \((?:last [0-9]+ characters|characters [0-9]+-[0-9]+; "
                    r"the rest was not captured)\))?:")


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
    denied: tuple[str, ...] = ()


RUN_PYTHON = ToolDefinition(
    "run_python",
    "Run Python 3 code in a throw-away folder and return what it prints; "
    "data files are in the current folder. Only the standard library is available "
    "(csv, statistics, json...; no pandas or numpy).",
    {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"],
     "additionalProperties": False},
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
            match = _OURS.fullmatch(entry.name)
            if match is None:
                continue
            try:
                if (not entry.is_dir(follow_symlinks=False)
                        or entry.stat(follow_symlinks=False).st_uid != os.getuid()):
                    continue
            except OSError:
                continue
            if _dead(match.group(1)):
                shutil.rmtree(entry.path, ignore_errors=True)


def _wanted(entry):
    """Visible, printable, non-importable regular file: no .env, no csv.py shadowing the stdlib.

    A name with a newline or another non-printable character is skipped, so it
    can never add a line to the model's prompt or report.
    """
    return (not entry.name.startswith(".") and entry.name.isprintable()
            and not entry.name.lower().endswith(_IMPORTABLE)
            and entry.is_file(follow_symlinks=False))


def _allowed(permission, path):
    """Fail closed: a refusal, an odd decision or any Exception keeps the file out."""
    if permission is None:
        return True
    try:
        return permission.check(PermissionRequest("read", path)).allowed is True
    except Exception:
        return False


def _listing(data_dir, permission):
    """Top-level regular data files of data_dir the permission allows, and the refused names."""
    if data_dir is None:
        return [], []
    path = os.fspath(data_dir)
    if not os.path.isdir(path):
        raise SandboxError(f"data folder not found: {path}")
    # One resolved folder to scan, to check and to open: the port sees the copied file.
    folder = os.path.realpath(path)
    try:
        with os.scandir(folder) as entries:
            files = sorted(filter(_wanted, entries), key=lambda e: e.name)
    except OSError as exc:
        raise SandboxError(f"cannot read data folder: {exc}") from exc
    allowed, denied = [], []
    for entry in files:
        (allowed if _allowed(permission, entry.path) else denied).append(entry)
    return allowed, [e.name for e in denied]


def _data_files(data_dir, limit, permission=None):
    """(path, name) of the files to copy, sorted, with their total size checked; refused names."""
    files, denied = _listing(data_dir, permission)
    try:
        total = sum(e.stat(follow_symlinks=False).st_size for e in files)
    except OSError as exc:
        raise SandboxError(f"cannot read data folder: {exc}") from exc
    if total > limit:
        raise SandboxError(f"data folder is larger than {limit / _MB:g} MB")
    return [(e.path, e.name) for e in files], tuple(denied)


def data_file_names(data_dir: str | os.PathLike | None,
                    permission: PermissionPort | None = None) -> list[str]:
    """Sorted names run_python would copy from data_dir (the size limit is checked per run)."""
    return [entry.name for entry in _listing(data_dir, permission)[0]]


def data_prompt(names: list[str]) -> str:
    """The system prompt line naming the data files (names only, never contents)."""
    if not names:
        return "The data folder has no files run_python can use."
    return f"Data files available to run_python: {', '.join(names)}."


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
        info = os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
        # macOS also reports a stopped (or continued) child here: that is not an exit.
        return info is not None and info.si_code in (os.CLD_EXITED, os.CLD_KILLED, os.CLD_DUMPED)
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
                # Start on a character: skip at most 3 UTF-8 continuation bytes.
                start = len(self.err) - self.cap
                end = min(start + 3, len(self.err))
                while start < end and 0x80 <= self.err[start] < 0xC0:
                    start += 1
                del self.err[:start]
                self.cut = True


def _collect(process, limits, token, guard):
    output = _Output(4 * limits.output_chars)
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, "out")
    selector.register(process.stderr, selectors.EVENT_READ, "err")
    deadline = monotonic() + limits.wall_seconds
    timed_out = False
    drain_until = None
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
            if exited and drain_until is None:
                # A grandchild may keep the pipes busy: the group kill ends it soon.
                drain_until = monotonic() + _DRAIN_SECONDS
            elif exited and monotonic() >= drain_until:
                output.cut = output.cut or bool(selector.get_map() and selector.select(0))
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
               limits: SandboxLimits = SandboxLimits(),
               permission: PermissionPort | None = None) -> SandboxRun:
    """Run code as main.py in a new temp folder; the folder never outlives the call.

    With ``permission``, each data file is copied only if
    ``permission.check(PermissionRequest("read", <path>))`` allows it, where
    the path is the one opened: the data folder resolved with ``realpath``
    plus the name. A refusal or an exception from the port leaves the file
    out, named in ``denied``.
    """
    if cancellation is not None:
        cancellation.raise_if_cancelled()
    remove_stale_folders()
    files, denied = _data_files(data_dir, limits.data_bytes, permission)
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
                      output.cut or cut_out or cut_err, denied)


def _status(run, limits):
    """The exit line, then the limit or signal that ended the run, if any."""
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
    return lines


def format_run(run: SandboxRun, limits: SandboxLimits = SandboxLimits()) -> str:
    lines = _status(run, limits)
    if run.truncated:
        lines.append("(output truncated)")
    for label, text in (("stdout", run.stdout), ("stderr", run.stderr)):
        if text:
            lines += [f"{label}:", text.rstrip("\n")]
    return "\n".join(lines)


def model_report(run: SandboxRun, limits: SandboxLimits = SandboxLimits()) -> str:
    """The tool result for the model: the end of each stream, then the fix-it line."""
    streams, cut = [], run.truncated
    # stdout is captured from its start: at the capture limit, its tail is not the end.
    head = run.truncated and len(run.stdout) >= limits.output_chars
    for label, text in (("stdout", run.stdout), ("stderr", run.stderr)):
        text = text.rstrip("\n")
        shown = text[-MODEL_CHARS:]
        if label == "stdout" and head and text:
            streams.append((f"stdout (characters {len(text) - len(shown) + 1}-{len(text)}; "
                            "the rest was not captured):", shown))
        elif len(text) > MODEL_CHARS:
            streams.append((f"{label} (last {MODEL_CHARS} characters):", shown))
            cut = True
        elif text:
            streams.append((f"{label}:", text))
    lines = _status(run, limits)
    if cut:
        lines.append("(output truncated)")
    for label, text in streams:
        lines += [label, text]
    if run.denied:
        lines.append(_NOT_ALLOWED + ", ".join(run.denied))
    lines.append(FIX_IT)
    return "\n".join(lines)


def report_summary(text: str) -> tuple[str, str | None]:
    """(first line, last non-empty stderr line on failure or stdout line on success).

    The second item is None when ``text`` is not a ``model_report`` or the
    stream is empty. Printed lines that look like stream labels can shift it.
    """
    lines = text.splitlines()
    first = lines[0] if lines else ""
    status = _STATUS.match(first)
    if status is None or len(lines) < 2 or lines[-1] != FIX_IT:
        return first, None
    body = lines[1:-1]
    if body and body[-1].startswith(_NOT_ALLOWED):
        body.pop()
    labels = [(i, match.group(1)) for i, line in enumerate(body)
              if (match := _LABEL.fullmatch(line))]
    # The first label is real, and only stderr text follows the last stderr label.
    errors = [i for i, name in labels if name == "stderr"]
    if int(status.group(1)) != 0:
        section = body[errors[-1] + 1:] if errors else []
    elif labels and labels[0][1] == "stdout":
        start = labels[0][0] + 1
        section = body[start:errors[-1] if errors and errors[-1] > start else len(body)]
    else:
        section = []
    return first, next((line for line in reversed(section) if line.strip()), None)


def python_tool(arguments, cancellation=None, *, data_dir=None,
                limits: SandboxLimits = SandboxLimits(),
                permission: PermissionPort | None = None, report=model_report) -> ToolResult:
    """run_python as a tool: ``report`` text, an error result if the code failed.

    ``report`` is ``model_report`` for the model or ``format_run`` for ``/run``.
    It and ``permission`` go to the tool's child process with the handler, so
    they must be pickleable (a module-level function or class instance).
    """
    try:
        run = run_python(arguments["code"], data_dir, cancellation, limits=limits,
                         permission=permission)
    except SandboxError as exc:
        return ToolResult("", str(exc))
    text = report(run, limits)
    return ToolResult(text, text if run.exit_code != 0 or run.timed_out else None)
