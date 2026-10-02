# Ollama usage and privacy-safe event hooks (T11 / #24, T13 / #26)

`OllamaClient` still implements the B1 streaming port and sends the same
`/api/chat` request. Both hooks are optional:

```python
from sensai.llm.ollama import OllamaClient
from sensai.observability.telemetry import BoundedEventSink

events = []
sink = BoundedEventSink(events.append, max_events=128)
usage = []
client = OllamaClient(event_sink=sink, usage_sink=usage.append)
# Consume client.stream(model, messages) to completion (or close it early).
sink.drain()  # Explicit delivery, including to a real metrics consumer.
```

`usage_sink` receives a frozen `OllamaUsage` per started request, including
error/cancellation outcomes. Its `prompt_tokens` and `output_tokens` are
`int | None`, taken *only* from Ollama's final `prompt_eval_count` and
`eval_count`. Missing counts remain `None`, including after failures or early
close; no estimate is made from text chunks. `latency_ms` is elapsed client
wall-clock time; optional `server_duration_ms` is Ollama's `total_duration`
converted from nanoseconds. Neither is a cost calculation. An EOF without
`done: true` raises `LLMError`, with `UsageError.INCOMPLETE_STREAM`. A caller
who closes a suspended stream gets `UsageError.CANCELLED` and the HTTP response
is closed, even if the last yielded chunk had `done: true`: success is reported
only after that final chunk is consumed. A generator never started cannot
produce usage or events.

The HTTP response is closed before reporting a successful completion. If
closing fails, the client reports `UsageError.TRANSPORT` and raises a sanitized
`LLMError` instead of recording success. If an Ollama error already occurred,
that primary error is preserved (with a sanitized close-failure note where
supported); raw close exception details are never sent to events.

`Telemetry` is a typed producer for `request.started/completed/failed/cancelled`
and `tool.started/completed/failed` events, interoperable with
`EventPort.emit(Event(...))`. Tool callers may use
`Telemetry(sink).tool_started(new_operation_id())` and
`tool_finished(operation_id, latency_ms, error=None)`; they must call the
latter on both success and failure. The client instruments only Ollama requests;
it does not intercept tool execution. Correlation IDs are random, not derived
from content. The allowlist permits only IDs, durations, reported token counts,
and enumerated error codes; no model name, raw prompt, response, tool name,
arguments, result, HTTP error body, or exception text is emitted. Remote HTTP
and stream error *messages* are not surfaced to the application either.

`BoundedEventSink` validates and copies events on `emit`, queues at most
`max_events` per instance (default 128), and delivers only on `drain()`. The
queue and returned events cannot be mutated through the caller's fields.
Queue overflow raises `EventDeliveryError`; it does not silently drop events.
If the subscriber fails, `drain()` raises `EventDeliveryError` and retains
the undelivered event for retry (at-least-once delivery: a subscriber that
partially processed it must be idempotent). Run `drain()` regularly from the
application's chosen worker/loop; there is no background worker. Subscriber
and usage callback failures propagate rather than being silently ignored.
Avoid collecting raw usage callback data or events in an unbounded list in
production.

These are opt-in hooks, **not** an EV3 dashboard, an EV2 guardrail, automatic
tool instrumentation, persistence, aggregation, or a guarantee of redaction
outside this event boundary. Consumers own retention, access control,
backpressure handling, and any privacy policy enforcement.
