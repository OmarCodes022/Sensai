"""run_python for the page: the CLI tool plus a JSON record of the run next to its text result.

The handler runs in a child process (as in the CLI), so it hands the structured
result back through a small file whose path the parent chose.
"""
import json
import os
import signal
import tempfile
from functools import partial

from sensai.core.cancellation import CancellationToken, OperationTimedOut
from sensai.core.errors import SensaiError
from sensai.core.ports import ToolCall, ToolResult
from sensai.sandbox import (
    RUN_PYTHON, SandboxError, SandboxLimits, SandboxRun, _FILE_TOO_LARGE, _MB,
    format_run, run_python,
)
from sensai.tools import ToolRegistry
from sensai_web.errors import ApiError

MAX_CODE_BYTES = 1024 * 1024


def run_record(run: SandboxRun, limits: SandboxLimits) -> dict:
    """What the page needs to draw a run: exit state, streams, flags and the limits in force."""
    record = {
        "exit_code": run.exit_code, "duration_s": round(run.duration, 3), "timed_out": run.timed_out,
        "truncated": run.truncated, "stdout": run.stdout, "stderr": run.stderr,
        "report": format_run(SandboxRun("", "", run.exit_code, run.duration, run.timed_out, run.truncated), limits),
        "limits": {"wall_seconds": limits.wall_seconds, "cpu_seconds": limits.cpu_seconds,
                   "memory_mb": limits.memory_bytes // _MB, "file_mb": limits.file_bytes // _MB},
        "cpu_exceeded": run.exit_code == -signal.SIGXCPU,
        "file_exceeded": run.exit_code == -signal.SIGXFSZ or bool(run.exit_code and _FILE_TOO_LARGE in run.stderr),
    }
    if run.exit_code < 0:
        try:
            record["signal"] = signal.Signals(-run.exit_code).name
        except ValueError:
            record["signal"] = str(-run.exit_code)
    return record


def web_python_tool(arguments, cancellation=None, *, data_dir=None, meta_path=None) -> ToolResult:
    """Same result text as the CLI's python_tool; also writes run_record() to meta_path."""
    limits = SandboxLimits()
    try:
        run = run_python(arguments["code"], data_dir, cancellation, limits=limits)
    except SandboxError as exc:
        return ToolResult("", str(exc))
    if meta_path is not None:
        temporary = f"{meta_path}.tmp"
        with open(temporary, "w", encoding="utf-8") as f:
            json.dump(run_record(run, limits), f, ensure_ascii=False)
        os.replace(temporary, meta_path)
    text = format_run(run, limits)
    return ToolResult(text, text if run.exit_code != 0 or run.timed_out else None)


def run_handler(data_dir: str | None, meta_path: str):
    return partial(web_python_tool, data_dir=data_dir, meta_path=meta_path)


def take_record(meta_path: str) -> dict | None:
    """Read and remove the record of the last run, or None if the run produced none."""
    try:
        with open(meta_path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None
    finally:
        for path in (meta_path, f"{meta_path}.tmp"):
            try:
                os.remove(path)
            except OSError:
                pass


def run_code(code: object, data_dir: str | None, token: CancellationToken, meta_dir: str) -> dict:
    """The Tools page runner: the timed worker path, without approval or chat history."""
    if not isinstance(code, str) or not code.strip():
        raise ApiError(400, "empty_code", "Type some Python first.")
    if len(code.encode("utf-8")) > MAX_CODE_BYTES:
        raise ApiError(413, "too_large", "The code is larger than 1 MiB.")
    fd, meta_path = tempfile.mkstemp(prefix="run-", suffix=".json", dir=meta_dir)
    os.close(fd)
    os.remove(meta_path)
    registry = ToolRegistry()
    registry.register(RUN_PYTHON, run_handler(data_dir, meta_path))
    try:
        result = registry.execute(ToolCall(RUN_PYTHON.name, {"code": code}), token)
    except SensaiError as exc:
        take_record(meta_path)
        if isinstance(exc, OperationTimedOut):
            raise ApiError(504, "run_timeout", "The run exceeded the time budget.") from None
        raise ApiError(500, "run_failed", str(exc)) from None
    record = take_record(meta_path)
    if record is None:
        raise ApiError(400, "sandbox", result.error or "The run produced no result.")
    return record
