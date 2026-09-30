"""Opt-in, bounded delivery of privacy-safe lifecycle events."""

from collections import deque
from collections.abc import Callable, Mapping
from enum import Enum
import math
import re
from threading import Lock
from types import MappingProxyType
from uuid import uuid4

from sensai.contracts import Event, EventPort, PortError
from sensai.llm.schemas import OllamaUsage, UsageError


class EventName(str, Enum):
    REQUEST_STARTED = "request.started"
    REQUEST_COMPLETED = "request.completed"
    REQUEST_FAILED = "request.failed"
    REQUEST_CANCELLED = "request.cancelled"
    TOOL_STARTED = "tool.started"
    TOOL_COMPLETED = "tool.completed"
    TOOL_FAILED = "tool.failed"


class EventDeliveryError(PortError):
    """The event queue is full or its subscriber could not accept an event."""


_REQUIRED = {
    EventName.REQUEST_STARTED: frozenset({"operation_id"}),
    EventName.REQUEST_COMPLETED: frozenset({"operation_id", "latency_ms"}),
    EventName.REQUEST_FAILED: frozenset({"operation_id", "latency_ms", "error_code"}),
    EventName.REQUEST_CANCELLED: frozenset({"operation_id", "latency_ms"}),
    EventName.TOOL_STARTED: frozenset({"operation_id"}),
    EventName.TOOL_COMPLETED: frozenset({"operation_id", "latency_ms"}),
    EventName.TOOL_FAILED: frozenset({"operation_id", "latency_ms", "error_code"}),
}
_OPTIONAL = {
    EventName.REQUEST_COMPLETED: frozenset(
        {"prompt_tokens", "output_tokens", "server_duration_ms"}
    ),
}
_HEX_ID = re.compile(r"[0-9a-f]{32}\Z")
_NUMBER = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z")
_COUNT = re.compile(r"(?:0|[1-9][0-9]*)\Z")


def new_operation_id() -> str:
    """Generate a random, non-content-derived correlation identifier."""
    return uuid4().hex


def _safe_event(event: Event) -> Event:
    try:
        name = EventName(event.name)
        fields = dict(event.fields)
        if not _REQUIRED[name] <= fields.keys() or not fields.keys() <= (
            _REQUIRED[name] | _OPTIONAL.get(name, frozenset())
        ):
            raise ValueError
        if not all(isinstance(value, str) for value in fields.values()):
            raise ValueError
        if not _HEX_ID.fullmatch(fields["operation_id"]):
            raise ValueError
        for key, value in fields.items():
            if key in {"latency_ms", "server_duration_ms"}:
                if len(value) > 32 or not _NUMBER.fullmatch(value):
                    raise ValueError
            elif key in {"prompt_tokens", "output_tokens"}:
                if len(value) > 20 or not _COUNT.fullmatch(value):
                    raise ValueError
            elif key == "error_code" and value not in {e.value for e in UsageError}:
                raise ValueError
    except (ValueError, KeyError, TypeError, AttributeError):
        raise ValueError("invalid or disallowed telemetry event") from None
    return Event(name.value, MappingProxyType(fields))


class BoundedEventSink(EventPort):
    """Queue validated events; drain to one subscriber, retaining failed deliveries.

    The queue is per instance. Backpressure is explicit rather than silently
    losing events. A failed subscriber leaves the first undelivered event queued.
    """

    def __init__(self, subscriber: Callable[[Event], None], max_events: int = 128):
        if type(max_events) is not int or max_events < 1:
            raise ValueError("max_events must be positive")
        self._subscriber = subscriber
        self._max_events = max_events
        self._pending: deque[Event] = deque()
        self._lock = Lock()
        self._draining = False

    @property
    def pending(self) -> int:
        with self._lock:
            return len(self._pending)

    def emit(self, event: Event) -> None:
        safe = _safe_event(event)
        with self._lock:
            if len(self._pending) >= self._max_events:
                raise EventDeliveryError("telemetry queue is full")
            self._pending.append(safe)

    def drain(self, limit: int | None = None) -> int:
        if limit is not None and limit < 1:
            raise ValueError("limit must be positive")
        with self._lock:
            if self._draining:
                raise EventDeliveryError("telemetry drain already running")
            self._draining = True
        delivered = 0
        try:
            while limit is None or delivered < limit:
                with self._lock:
                    if not self._pending:
                        break
                    event = self._pending[0]
                try:
                    self._subscriber(event)
                except Exception:
                    raise EventDeliveryError("telemetry subscriber failed") from None
                with self._lock:
                    self._pending.popleft()
                delivered += 1
        finally:
            with self._lock:
                self._draining = False
        return delivered


def _duration(value: float) -> str:
    if not math.isfinite(value) or value < 0:
        raise ValueError("invalid telemetry duration")
    return str(value)


class Telemetry:
    """Typed producers: never accept arbitrary payloads or exception messages."""

    def __init__(self, sink: EventPort):
        self._sink = sink

    def _emit(self, name: EventName, fields: Mapping[str, str]) -> None:
        self._sink.emit(_safe_event(Event(name.value, fields)))

    def request_started(self, operation_id: str) -> None:
        self._emit(EventName.REQUEST_STARTED, {"operation_id": operation_id})

    def request_finished(self, operation_id: str, usage: OllamaUsage) -> None:
        fields = {
            "operation_id": operation_id,
            "latency_ms": _duration(usage.latency_ms),
        }
        if usage.error is None:
            if usage.prompt_tokens is not None:
                fields["prompt_tokens"] = str(usage.prompt_tokens)
            if usage.output_tokens is not None:
                fields["output_tokens"] = str(usage.output_tokens)
            if usage.server_duration_ms is not None:
                fields["server_duration_ms"] = _duration(usage.server_duration_ms)
            name = EventName.REQUEST_COMPLETED
        elif usage.error == UsageError.CANCELLED:
            name = EventName.REQUEST_CANCELLED
        else:
            fields["error_code"] = usage.error.value
            name = EventName.REQUEST_FAILED
        self._emit(name, fields)

    def tool_started(self, operation_id: str) -> None:
        self._emit(EventName.TOOL_STARTED, {"operation_id": operation_id})

    def tool_finished(
        self, operation_id: str, latency_ms: float, error: UsageError | None = None
    ) -> None:
        fields = {"operation_id": operation_id, "latency_ms": _duration(latency_ms)}
        if error is not None:
            fields["error_code"] = error.value
        self._emit(
            EventName.TOOL_FAILED if error is not None else EventName.TOOL_COMPLETED,
            fields,
        )
