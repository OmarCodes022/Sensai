"""Importable handlers for real spawned-tool tests; no external services."""

import os
from pathlib import Path
import subprocess
import sys
import time

from sensai.core.cancellation import OperationCancelled, OperationTimedOut
from sensai.core.ports import ToolResult


class WorkerAbort(BaseException):
    pass


def exercise(arguments, cancellation=None):
    action = arguments.get("action", "success")
    if action == "pid":
        return ToolResult(str(os.getpid()))
    if action == "error":
        return ToolResult("partial", "explicit failure")
    if action == "raise":
        raise ValueError("bad tool input")
    if action == "timeout":
        raise OperationTimedOut("handler deadline")
    if action == "cancel":
        raise OperationCancelled("handler cancellation")
    if action == "keyboard":
        raise KeyboardInterrupt()
    if action == "exit":
        raise SystemExit(2)
    if action == "generator":
        raise GeneratorExit()
    if action == "base":
        raise WorkerAbort()
    if action == "invalid":
        return "wrong result"
    if action == "invalid_field":
        return ToolResult("", 7)
    if action == "descendant":
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        Path(arguments["marker"]).write_text(f"{os.getpid()}:{child.pid}")
        time.sleep(30)
    if action == "block":
        time.sleep(30)
    return ToolResult("complete")
