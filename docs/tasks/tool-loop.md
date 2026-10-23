# Tool loop (T18)

Sensai can execute the `calculate` arithmetic tool and use its result in an
answer without native model tool calling. `/tools` lists the registered
names and descriptions without contacting the model. Additional tools can
register the existing `ToolDefinition` and handler contract; file access,
Python execution, web search, MCP and other later tasks are not implemented
by this loop.

## Reply protocol

A model requests a tool by ending its reply with a strict JSON object that
starts at column zero on its own line, with optional trailing whitespace:

```text
I'll calculate that.
{"tool": "calculate", "arguments": {"expression": "(14 + 6) / 100"}}
```

`BlockReader` holds a possible final object during streaming and releases
text if a decoded object is followed by more text. `finish()` returns the
**full** visible reply and the final object, so callers print only its
not-yet-emitted suffix. `split_block` uses the same final-block rules.
Malformed JSON, NaN, Infinity, overflowing JSON numbers, inline objects and
objects followed by text remain visible. Valid final objects are hidden;
non-tool objects are returned unchanged to the caller.

`parse_tool_call` requires a nonblank string `tool` and an optional JSON
object `arguments` (default `{}`). Direct calls and decoded arguments must
contain only finite JSON values, with string object keys.

## Registry and handlers

`ToolRegistry(approval=None, *, read=input)` satisfies `ToolPort` and retains
the existing `register`, `definitions` and `execute` signatures. Definitions
keep insertion order. Registration rejects blank/duplicate names,
noncallable handlers, invalid timeouts and invalid per-question limits.

```python
registry.register(DEFINITION, handler, timeout=30.0, confirm=False, max_calls=None)
```

A handler takes `(arguments, cancellation)` and returns
`ToolResult(output: str, error: str | None = None)`. The registry checks
required properties and the basic JSON types `string`, `number`, `integer`,
`boolean`, `array`, `object` and `null`. Booleans are distinct from numbers
and integers. This is a schema subset, not a full JSON Schema validator.
Unknown tools, invalid arguments, refused approval, exhausted limits, wrong
result types/fields and ordinary handler exceptions produce short error
results. Global cancellation/deadlines and non-`Exception` control failures
propagate.

Each attempted known-tool call consumes its per-question count, including
bad arguments and refused approval. `max_calls=None` is unlimited;
`max_calls=0` disables execution. Counts live in the parent and reset once
at the start of `run_with_tools`.

### Numeric deadlines: child processes

A positive finite numeric timeout uses the existing spawn-based
`ControlledTool`. Process startup counts toward the local deadline, which
starts **after approval**. The effective deadline is the earlier of the
local and question deadlines. A local expiry becomes a tool error; the
original question token is rechecked after process cleanup so global
cancellation or expiry still propagates. A handler-raised `OperationTimedOut`
before either deadline propagates, even if cleanup later crosses the local
deadline.

Timed handlers must be importable/pickleable module functions or callable
instances with serializable configuration. Registration checks
`pickle.dumps`; this cannot guarantee importability in a new process, and
startup failures become tool errors. Open DB connections, files and other
resources **inside the child**. Parent in-memory mutations are not shared.
The worker process group and descendants are stopped after success,
failure, cancellation or timeout. This isolates execution lifetime; it is
not a filesystem/network permission sandbox.

The IPC preserves `ToolResult.output` and `error`, plus cancellation and
control failures. `KeyboardInterrupt`, `SystemExit` and `GeneratorExit`
retain their public families; unknown non-`Exception` failures become a
plain `BaseException` without deserializing arbitrary classes. Existing LLM
worker error behavior is unchanged.

### Approval and interactive tools

`confirm=True` asks the supplied `ApprovalPort` with
`ApprovalRequest(action=name, resource=JSON arguments, reason=description)`.
Without it, the injected reader asks `[y/N]`: `y`, `yes`, `o` and `oui`
(case-insensitive) permit execution; other answers and EOF refuse. The CLI
injects `TerminalInput.read`, so approval works in its raw terminal mode.
Approval happens in the parent before spawning and pauses the question
budget while the user answers.

`timeout=None` executes in the parent for interactive tools. The original
token temporarily has no deadline, and its deadline is extended by elapsed
time in `finally`, including on failure. Its cancellation state and callback
remain the same. Neither the registry nor the handler should poll the
terminal cancellation callback while reading: that callback consumes pending
keys. Such a handler may catch its own `KeyboardInterrupt` and return a
skipped result; otherwise control exceptions propagate.

## Question loop and history

`run_with_tools(session, registry, text, cancellation=None, *, max_rounds=5,
on_tool=None)` reuses `ChatSession.send`, yields only visible model text and
returns `(last_visible_reply, non_tool_block_or_None)`.

Every parsed block containing a `tool` key consumes a round, including
malformed/unknown calls. `max_rounds` must be an integer of at least one.
After the last round, the next request contains its result and an
instruction to give a final answer without tools. At most `max_rounds + 1`
model replies occur; a final tool block is hidden and never executed.

`on_tool(call, result)` runs once per completed tool round, before the result
is sent. A malformed call uses `ToolCall("<invalid>", {})`. The CLI prints
`Using tool: ...`; other clients can supply their own observer. Results use
the existing user message role, clearly prefixed `Tool result from ...` or
`Tool error from ...`, so the saved message schema is unchanged.

A cancelled, timed-out, failed or closed question first closes the active
stream, then removes **all** history added by that question. Observer
failures also roll back the question. Already-performed external tool effects
cannot be undone. Persistence occurs only after the whole loop completes,
with successful tool rounds preserved for resume. Session title generation
uses the first final visible answer rather than an intermediate tool call;
a failed save retains the existing retry behavior.

The CLI appends current registry instructions once to its initial prompt
and each persona prompt, preserving creator profile/custom instructions and
completed history. One registry serves the conversation.

## Calculator and verification

`calculate` accepts a required string `expression`, capped at 1024
characters before parsing. It uses `ast` (never `eval`) for numeric constants,
unary `+`/`-`, binary `+`/`-`/`*`/`/` and parentheses. Booleans, names, calls,
attributes, other operators and nonfinite values/results are rejected.
Numeric execution is isolated like other timed tools.

Offline tests use scripted model replies, fake approvals/terminals and real
spawned processes. No model or network is required:

```sh
PYTHONPATH=src:tests/helpers .venv/bin/python -m pytest -q tests/unit
```
