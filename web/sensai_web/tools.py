"""The tool registry of one web turn, reporting each call as stream events."""
import os
import tempfile
from collections.abc import Callable
from functools import partial
from time import monotonic

from sensai.core.ports import ToolCall, ToolResult
from sensai.rag import SEARCH_DOCS, DocLibrary, search_with_hits
from sensai.sandbox import PYTHON_ATTEMPTS, RUN_PYTHON
from sensai.chat.facts import DELETE_FACT, SAVE_FACT, FactMemory
from sensai.chat.questions import ASK_USER
from sensai.search import WEB_SEARCH
from sensai.security.file_tools import FILE_TOOLS, FileTools
from sensai.tools import CALCULATE, ToolRegistry, calculate
from sensai_web.approvals import WebApproval
from sensai_web.sandbox import run_handler, take_record
from sensai_web.session_view import for_page

# What the page's Tools view lists: name -> (timeout seconds, needs approval, calls per question).
TOOL_TABLE = {CALCULATE.name: (30, False, None), RUN_PYTHON.name: (30, True, PYTHON_ATTEMPTS),
              SEARCH_DOCS.name: (None, False, None), SAVE_FACT.name: (None, False, None),
              DELETE_FACT.name: (None, False, None), **{d.name: (None, False, None) for d in FILE_TOOLS},
              ASK_USER.name: (None, False, None), WEB_SEARCH.name: (None, False, None)}
INVALID = "<invalid>"


def tool_list(documents: bool = False, files: bool = False, web: bool = False) -> list[dict]:
    return [{"name": d.name, "description": d.description, "parameters": d.parameters,
             "timeout": TOOL_TABLE[d.name][0], "confirm": TOOL_TABLE[d.name][1], "max_calls": TOOL_TABLE[d.name][2]}
            for d in (CALCULATE, RUN_PYTHON, SAVE_FACT, DELETE_FACT, *((SEARCH_DOCS,) if documents else ()),
                      *(FILE_TOOLS if files else ()), ASK_USER, *((WEB_SEARCH,) if web else ()))]


class ObservedRegistry(ToolRegistry):
    """Emits tool_call before and tool_result after every call (approvals emit their own events).

    For a tool with a call limit, both events carry ``attempt`` (this call's number in the
    question) and ``max_attempts``; the call refused after the limit has ``attempt > max_attempts``.
    """

    def __init__(self, approval: WebApproval, emit: Callable[[dict], None], data_dir: str | None,
                 meta_dir: str, library: DocLibrary | None = None, memory: FactMemory | None = None,
                 files: FileTools | None = None, form=None, web=None):
        super().__init__(approval)
        self._approval = approval
        self._emit = emit
        self._round = 0
        fd, self._meta_path = tempfile.mkstemp(prefix="turn-", suffix=".json", dir=meta_dir)
        os.close(fd)
        os.remove(self._meta_path)
        self.register(CALCULATE, calculate)
        self.register(RUN_PYTHON, run_handler(data_dir, self._meta_path, permission=None), confirm=True,
                      max_calls=PYTHON_ATTEMPTS)  # No permission policy yet (T26).
        if memory is not None:  # In this process: the queue of fact changes is here.
            self.register(SAVE_FACT, memory.save, timeout=None)
            self.register(DELETE_FACT, memory.delete, timeout=None)
        for definition in (FILE_TOOLS if files is not None else ()):  # In this process, with the loaded policy.
            self.register(definition, getattr(files, definition.name), timeout=None)
        if form is not None:  # Waits for the page in this process.
            self.register(ASK_USER, form, timeout=None)
        if web is not None:  # Keeps this turn's results here for the source list.
            self.register(WEB_SEARCH, web, timeout=None)
        self._hits: list[dict] = []
        if library is not None and library.enabled:
            self.register(SEARCH_DOCS, partial(self._search, library), timeout=None)  # In this process: the index is here.

    def execute(self, call: ToolCall, cancellation=None) -> ToolResult:
        call_id = self._announce(call)
        self._approval.call_id = call_id
        waited, started = self._approval.waited, monotonic()
        result = super().execute(call, cancellation)  # Cancellation propagates: no result event.
        elapsed = monotonic() - started - (self._approval.waited - waited)
        self._report(call_id, call, result, int(elapsed * 1000))
        return result

    def _search(self, library: DocLibrary, arguments, cancellation=None) -> ToolResult:
        text, self._hits = search_with_hits(library, arguments.get("query", ""))
        return ToolResult(text)

    def malformed(self, call: ToolCall, result: ToolResult) -> None:
        """A tool block the loop could not parse or run still shows as a failed call."""
        self._report(self._announce(call), call, result, 0)

    def _attempt(self, event: dict, name: str, ahead: int) -> dict:
        calls, limit = self.usage(name)
        if limit:  # A limit of 0 never runs, so there is nothing to number.
            event.update(attempt=calls + ahead, max_attempts=limit)
        return event

    def _announce(self, call: ToolCall) -> str:
        self._round += 1
        call_id = f"c{self._round}"
        self._emit(self._attempt({"type": "tool_call", "id": call_id, "name": call.name,
                                  "arguments": dict(call.arguments), "round": self._round}, call.name, 1))
        return call_id

    def _report(self, call_id: str, call: ToolCall, result: ToolResult, duration_ms: int) -> None:
        # The model already got the whole report; the page shows it without the line meant for the model.
        event = self._attempt({"type": "tool_result", "id": call_id, "name": call.name, "ok": result.error is None,
                               "error": for_page(call.name, result.error), "output": for_page(call.name, result.output),
                               "duration_ms": duration_ms}, call.name, 0)
        record = take_record(self._meta_path) if call.name == RUN_PYTHON.name else None
        if record is not None:
            event["duration_ms"] = int(record["duration_s"] * 1000)
            event["meta"] = {key: record[key] for key in record if key not in ("report", "duration_s")}
        self._emit(event)
        if call.name == SEARCH_DOCS.name and result.error is None and self._hits:
            self._emit({"type": "sources", "items": [{k: hit[k] for k in ("n", "source", "version", "score", "outdated")} for hit in self._hits]})
            self._hits = []

    def close(self) -> None:
        take_record(self._meta_path)
