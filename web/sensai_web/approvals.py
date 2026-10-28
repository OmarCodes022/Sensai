"""Human approval over HTTP: the turn waits here until POST /api/approvals/{id} answers."""
import json
import re
from collections.abc import Callable
from threading import Event, Lock
from time import monotonic

from sensai.cli.approval import sanitize
from sensai.core.ports import ApprovalDecision, ApprovalRequest

PREVIEW_LINES = 6
LINE_WIDTH = 160
_LONE_CR = re.compile("\r(?!\n)")


class Approvals:
    """Pending requests by id, shared between the waiting turn and the answering request."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._pending: dict[str, tuple[Event, list[bool]]] = {}

    def open(self, approval_id: str) -> tuple[Event, list[bool]]:
        slot = (Event(), [False])
        with self._lock:
            self._pending[approval_id] = slot
        return slot

    def decide(self, approval_id: str, approved: bool) -> bool:
        with self._lock:
            slot = self._pending.get(approval_id)
        if slot is None:
            return False
        slot[1][0] = approved
        slot[0].set()
        return True

    def close(self, approval_id: str) -> None:
        with self._lock:
            self._pending.pop(approval_id, None)


def _lines(text: str) -> list[str]:
    # Python ends a source line at a lone \r too: show the break and the escaped \r.
    return [sanitize(line) for line in _LONE_CR.sub("\r\n", text).split("\n")]


def preview(resource: str) -> dict:
    """The arguments as escaped lines, cut like the terminal prompt (6 lines of 160 characters)."""
    try:
        arguments = json.loads(resource)
    except (ValueError, RecursionError):
        arguments = None
    if isinstance(arguments, dict):
        rows = [(f"{sanitize(str(key), keep='')}:", line)
                for key, value in arguments.items()
                for line in (_lines(value) if isinstance(value, str)
                             else [sanitize(json.dumps(value, ensure_ascii=False, separators=(",", ":")))])]
    else:
        rows = [("", line) for line in _lines(resource)]
    shown = rows[:PREVIEW_LINES]
    cut = any(len(text) > LINE_WIDTH for _, text in shown)
    lines = [{"header": header, "text": text[:LINE_WIDTH - 1] + "…" if len(text) > LINE_WIDTH else text}
             for header, text in shown]
    hidden = len(rows) - len(shown)
    return {"lines": lines, "hidden_lines": hidden, "incomplete": bool(hidden or cut)}


class WebApproval:
    """ApprovalPort for one turn: announces the request, then waits for the page or a stop."""

    def __init__(self, approvals: Approvals, emit: Callable[[dict], None], stop: Event, turn_id: str):
        self._approvals = approvals
        self._emit = emit
        self._stop = stop
        self._turn_id = turn_id
        self._count = 0
        self.call_id: str | None = None  # Set by the observing registry before each call.
        self.waited = 0.0  # Seconds spent waiting for the person, excluded from tool durations.

    def request(self, request: ApprovalRequest) -> ApprovalDecision:
        self._count += 1
        approval_id = f"{self._turn_id}-a{self._count}"
        done, answer = self._approvals.open(approval_id)
        # No `reason`: the page words it itself, in the language of its interface.
        self._emit({"type": "approval_request", "id": approval_id, "call_id": self.call_id,
                    "action": request.action, "preview": preview(request.resource)})
        started = monotonic()
        approved = False
        try:
            while not self._stop.is_set():
                if done.wait(0.1):
                    approved = answer[0]
                    break
        finally:
            self._approvals.close(approval_id)
            self.waited += monotonic() - started
        self._emit({"type": "approval_result", "id": approval_id, "approved": approved})
        return ApprovalDecision(approved)
