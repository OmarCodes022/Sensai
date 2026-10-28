"""The tool registry of one web turn, reporting each call as stream events."""
import os
import tempfile
from collections.abc import Callable
from time import monotonic

from sensai.core.ports import ToolCall, ToolResult
from sensai.sandbox import RUN_PYTHON
from sensai.tools import CALCULATE, ToolRegistry, calculate
from sensai_web.approvals import WebApproval
from sensai_web.sandbox import run_handler, take_record

# What the page's Tools view lists: name -> (timeout seconds, needs approval).
TOOL_TABLE = {CALCULATE.name: (30, False), RUN_PYTHON.name: (30, True)}
INVALID = "<invalid>"


def tool_list() -> list[dict]:
    return [{"name": d.name, "description": d.description, "parameters": d.parameters,
             "timeout": TOOL_TABLE[d.name][0], "confirm": TOOL_TABLE[d.name][1], "max_calls": None}
            for d in (CALCULATE, RUN_PYTHON)]


class ObservedRegistry(ToolRegistry):
    """Emits tool_call before and tool_result after every call (approvals emit their own events)."""

    def __init__(self, approval: WebApproval, emit: Callable[[dict], None], data_dir: str | None,
                 meta_dir: str):
        super().__init__(approval)
        self._approval = approval
        self._emit = emit
        self._round = 0
        fd, self._meta_path = tempfile.mkstemp(prefix="turn-", suffix=".json", dir=meta_dir)
        os.close(fd)
        os.remove(self._meta_path)
        self.register(CALCULATE, calculate)
        self.register(RUN_PYTHON, run_handler(data_dir, self._meta_path), confirm=True)

    def execute(self, call: ToolCall, cancellation=None) -> ToolResult:
        call_id = self._announce(call)
        self._approval.call_id = call_id
        waited, started = self._approval.waited, monotonic()
        result = super().execute(call, cancellation)  # Cancellation propagates: no result event.
        elapsed = monotonic() - started - (self._approval.waited - waited)
        self._report(call_id, call, result, int(elapsed * 1000))
        return result

    def malformed(self, call: ToolCall, result: ToolResult) -> None:
        """A tool block the loop could not parse or run still shows as a failed call."""
        self._report(self._announce(call), call, result, 0)

    def _announce(self, call: ToolCall) -> str:
        self._round += 1
        call_id = f"c{self._round}"
        self._emit({"type": "tool_call", "id": call_id, "name": call.name,
                    "arguments": dict(call.arguments), "round": self._round})
        return call_id

    def _report(self, call_id: str, call: ToolCall, result: ToolResult, duration_ms: int) -> None:
        event = {"type": "tool_result", "id": call_id, "name": call.name, "ok": result.error is None,
                 "error": result.error, "output": result.output, "duration_ms": duration_ms}
        record = take_record(self._meta_path) if call.name == RUN_PYTHON.name else None
        if record is not None:
            event["duration_ms"] = int(record["duration_s"] * 1000)
            event["meta"] = {key: record[key] for key in record if key not in ("report", "duration_s")}
        self._emit(event)

    def close(self) -> None:
        take_record(self._meta_path)
