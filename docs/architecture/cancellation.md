# T12: cancellation and total deadlines

`CancellationToken(deadline=None, cancel_requested=None)` carries one absolute
`time.monotonic()` deadline through all operation stages. Its optional polling
callback runs only in the parent. Cancellation raises `OperationCancelled`;
deadline expiry raises the separate `OperationTimedOut`. Both are `SensaiError`.
All stream/conversation/tool ports accept optional `cancellation`; omitted
arguments remain supported. Never reset the budget when dispatching an operation.

`ChatSession` checks the token before dispatch and immediately before committing.
It closes its backend generator and rolls back every incomplete turn, including
caller close, exceptions and interruption. Persistence adapters save only after
successful exhaustion; text already printed cannot be retracted.

Ollama calls with a token run through `ControlledLLMClient(factory,
event_sink=None, usage_sink=None)` in `sensai.core.execution`. The factory must
be pickleable/importable and return a client in a fresh spawned process. Calls
without a token preserve the direct synchronous API. A POSIX process group owns
the worker and its descendants. The parent polls a socketpair at most every
20 ms; newline-delimited JSON carries chunks, usage and typed errors.
Closing, cancelling or expiring the stream sends SIGTERM, waits at most 200 ms,
then sends SIGKILL and reaps the worker. Channels are fresh for every operation.
The isolation supports interruption; it is not a security sandbox.

Callbacks and privacy-safe request lifecycle events execute synchronously in the
parent. They must stay local and return promptly; blocking callbacks are not
interruptible worker operations. Request telemetry describes backend completion,
not turn persistence: a callback can cancel or fail after the backend completes,
in which case its `request.completed` event remains valid while `ChatSession`
rolls back the turn. Callers must use successful session exhaustion, not a request
event, to decide whether a turn may be saved.
Exactly one terminal usage/event is produced, including cancellation or deadline
expiry; token counts are absent if an interrupted request did not complete.
Known model/connection errors retain their public exception classes. An unexpected
worker exit is failure, never a completed answer. Server-side generation after
a closed connection is independent of the local worker lifetime.

`ControlledTool(factory).execute(call, cancellation=None)` constructs the tool
inside its own worker and forwards the original deadline. Factories must not
capture open database connections or live resources. Authorization precedes
execution; this adapter supplies neither permission checks, MCP nor sandboxing.

The terminal uses POSIX `termios`, restores its previous state on every exit,
and reads UTF-8 incrementally. Lone Escape has a 50-ms discrimination window;
arrow/CSI/SS3 sequences are ignored. Piped input retains line reading. The CLI
streams responses without a cancellation hint or screen redraws.

Run offline acceptance checks with:

```bash
python -m pytest tests/unit/test_t12_acceptance.py tests/unit/test_t12_terminal.py -q
```
