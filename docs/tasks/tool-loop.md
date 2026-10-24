# Tool loop (T18)

Sensai can execute the `calculate` arithmetic tool and use its result in an
answer without native model tool calling (the default model, `gemma3:1b`,
has none). `/tools` lists the registered names and descriptions without
contacting the model. Later tasks add tools by registering a
`ToolDefinition` and a handler (see "How later tasks plug in"); none of them
changes the loop.

## Reply protocol

A model requests a tool by ending its reply with a strict JSON object that
starts at column zero on its own line, with optional trailing whitespace:

```text
I'll calculate that.
{"tool": "calculate", "arguments": {"expression": "(14 + 6) / 100"}}
```

`BlockReader` (`src/sensai/chat/blocks.py`, reusable by other block-based
features) holds back output from a line starting with `{` while more text
could still make it the final object, so the user never sees the raw block.
It releases that line as soon as it can no longer be one: a decoded object
followed by more text, or a JSON error that is not explained by the end of
the buffer (anything but a cut string, escape, number or literal). The body
of a held string argument is checked incrementally, so long string arguments
stream in linear time; other held JSON is re-parsed on each chunk, which is
fine for normal tool-call sizes (a 22 KB pretty-printed block costs about
0.27 s in 4-character chunks, 88 KB about 4.5 s).
`feed(chunk)` returns the text safe to print now. `finish()` returns the
**full** visible reply and the final object, so callers print only its
not-yet-emitted suffix. `split_block(reply)` applies the same final-block
rules to a complete reply. Malformed JSON, NaN, Infinity, overflowing JSON
numbers, inline objects and objects followed by text remain visible. Valid
final objects are hidden; non-tool objects are returned unchanged to the
caller (see "Other blocks").

`parse_tool_call` requires a nonblank string `tool` and an optional JSON
object `arguments` (default `{}`), and raises `ValueError` otherwise. Direct
calls and decoded arguments must contain only finite JSON values, with
string object keys.

## Registry and handlers

`ToolRegistry(approval=None, *, read=input)` satisfies `ToolPort`;
`ToolRegistry()` keeps working. Definitions keep insertion order.
Registration rejects blank/duplicate names, noncallable handlers, invalid
timeouts and invalid per-question limits with `ValueError`.

```python
registry.register(DEFINITION, handler, timeout=30.0, confirm=False, max_calls=None)
registry.register(CALCULATE, calculate)                    # T18: timed, in a child process
registry.register(RUN_PYTHON, partial(python_tool, data_dir=data_dir),
                  confirm=True)                            # T19, sensai.sandbox
registry.register(ASK_USER, ask_user, timeout=None)        # T28: reads the terminal
registry.register(SAVE_FACT, save_fact, timeout=None)      # T32: needs in-memory state
```

A handler takes `(arguments, cancellation)` and returns
`ToolResult(output: str, error: str | None = None)`. The registry checks
`parameters` before approval: `required` properties, the basic JSON types
`string`, `number`, `integer`, `boolean`, `array`, `object` and `null` in
`properties`, and, only when the schema says `"additionalProperties": false`,
that every argument is listed in `properties` (else
`invalid arguments: unexpected property <name>`). Schemas without that key
accept extra arguments. Booleans are distinct from numbers and integers.
This is a schema subset, not a full JSON Schema validator.

Unknown tools, invalid arguments, refused approval, exhausted limits, local
timeouts, wrong result types/fields and ordinary handler exceptions produce
short error results; tool errors never crash the chat. Global cancellation
and deadlines propagate (see the rules below).

Each attempted known-tool call consumes its per-question count, including
bad arguments and refused approval. `max_calls=None` is unlimited;
`max_calls=0` disables execution. Counts live in the parent and reset once
at the start of `run_with_tools` (`start_question()`).

### Numeric deadlines: child processes

A positive finite numeric timeout uses the existing spawn-based
`ControlledTool`. Process startup counts toward the local deadline, which
starts **after approval**. The effective deadline is the earlier of the
local and question deadlines. A local expiry becomes a tool error; the
original question token is rechecked after process cleanup so global
cancellation or expiry still propagates. A handler-raised `OperationTimedOut`
before either deadline propagates, even if cleanup later crosses the local
deadline; a handler-raised `OperationCancelled` propagates too.

Timed handlers must be importable/pickleable module functions or callable
instances with serializable configuration. Registration checks
`pickle.dumps`; this cannot guarantee importability in a new process, and
startup failures become tool errors. Open DB connections, files and other
resources **inside the child**. Parent in-memory mutations are not shared:
tools that need in-memory state (T26 files, T32 facts, T36 document index)
register with `timeout=None`. The worker process group and descendants are
stopped after success, failure, cancellation or timeout. This isolates
execution lifetime; it is not a filesystem/network permission sandbox.

The IPC preserves `ToolResult.output` and `error`, plus cancellation and
handler timeouts. A `KeyboardInterrupt`, `SystemExit`, `GeneratorExit` or
other non-`Exception` raised by a handler in its child process becomes a
tool error (`PortError: tool handler raised <name>`): only the child
stopped, the main process was not interrupted. Arbitrary exception classes
are never deserialized. Existing LLM worker error behavior is unchanged.

### Approval and interactive tools

`confirm=True` asks the supplied `ApprovalPort` with
`ApprovalRequest(action=name, resource=JSON arguments, reason=description)`
and runs only if `ApprovalDecision.approved` (T19 adds `TerminalApproval`
in `src/sensai/cli/approval.py`, which T46 reuses). Without it, the
injected reader asks `[y/N]`: `y`, `yes`, `o` and `oui` (case-insensitive)
permit execution; other answers and EOF refuse. The CLI injects `TerminalInput.read`, so approval works in its
raw terminal mode. Approval happens in the parent before spawning and
pauses the question budget while the user answers.

`timeout=None` executes in the parent, for interactive tools that read the
terminal (child processes cannot) and tools that need in-memory state. The
original token temporarily has no deadline, and its deadline is extended by
elapsed time in `finally`, including on failure. Its cancellation state and
callback remain the same. Neither the registry nor the handler should poll
the terminal cancellation callback while reading (directly or through
`raise_if_cancelled()`): that callback discards unrecognised pending keys
(`src/sensai/cli/terminal.py`). Interactive tools such as `ask_user` catch
their own `KeyboardInterrupt` while reading and return a result such as
`ToolResult("user skipped the question")`, so the question continues.
Otherwise control exceptions raised in the main process (`KeyboardInterrupt`,
...) propagate and cancel the question.

## Question loop and history

`run_with_tools(session, registry, text, cancellation=None, *, max_rounds=5,
on_tool=None)` reuses `ChatSession.send`, yields only visible model text and
returns `(last_visible_reply, non_tool_block_or_None)`.

Every parsed block containing a `tool` key consumes a round, including
malformed/unknown calls. `max_rounds` must be an integer of at least one
(else `ValueError`); T20 lowers it to fit its step budget. After the last
round, the next request contains its result and an instruction to give a
final answer without tools. At most `max_rounds + 1` model replies occur; a
final tool block is hidden and never executed.

`on_tool(call, result)` runs once per completed tool round, before the result
is sent. A malformed call uses `ToolCall("<invalid>", {})`. The CLI prints
`Using tool: <name>(<arguments as compact JSON>)` on its own line; T20 prints
its "Act" and "Observe" lines. Results use the existing user message role,
clearly prefixed `Tool result from <name>:` or `Tool error from <name>:`, so
the saved message schema is unchanged.

A cancelled, timed-out, failed or closed question (any exception, including
`OperationCancelled`, `OperationTimedOut`, `LLMError`, `KeyboardInterrupt`,
or `close()`/`GeneratorExit`) first closes the active stream, then removes
**all** history added by that question, completed tool rounds included.
Observer failures also roll back the question. Already-performed external
tool effects cannot be undone. Persistence occurs only after the whole loop
completes, with successful tool rounds preserved for resume. Session title
generation uses the first final visible answer rather than an intermediate
tool call; a failed save retains the existing retry behavior.

The CLI appends current registry instructions once to its initial prompt
and each persona prompt, preserving creator profile/custom instructions and
completed history. One registry serves the conversation.

## Other blocks

`run_with_tools` executes only blocks that have a `"tool"` key. Any other
valid final block ends the loop and is returned to the caller unchanged:

```python
visible, block = yield from run_with_tools(session, registry, text)
if block is not None:
    ...  # handled by the caller
```

## How later tasks plug in

Each registers a `ToolDefinition` and a handler; none of them changes the
loop. Tools that need in-memory state register with `timeout=None`, since a
timed handler runs in a fresh process that shares nothing with the chat.

- T19: `run_python` (sandboxed code execution), registered as
  `partial(python_tool, data_dir=...)` from `sensai.sandbox` with `confirm=True`.
- T41: `web_search`.
- T28: `ask_user` (ask the user a question), `timeout=None`.
- T26: `read_file` / `write_file` / `create_file`, backed by `FileSystemPort`
  ([filesystem brief](filesystem-permissions.md)); permission checks stay in
  the handler; `timeout=None`.
- T42: MCP tools, each mapped to a `ToolDefinition`.
- T32: `save_fact` / `delete_fact` (brand fact sheet in SQLite), `timeout=None`.
- T36: document index tools, `timeout=None`.
- T21 (self-fixing code) and T20 (reasoning loop with tools) call
  `run_with_tools`; T20 passes `on_tool` and `max_rounds`.

## Calculator

`calculate` accepts a required string `expression`, capped at 1024
characters before parsing. It uses `ast` (never `eval`) for numeric constants,
unary `+`/`-`, binary `+`/`-`/`*`/`/` and parentheses. Booleans, names, calls,
attributes, other operators and nonfinite values/results are rejected.
Numeric execution is isolated like other timed tools.

## Tests

Offline tests use scripted model replies (fake sessions/clients), fake
approvals/terminals, importable handlers and real spawned processes; no
live model or network. They cover: streamed blocks split across every chunk
boundary; invalid, non-final, inline and non-tool blocks; earlier `{` lines
that never become JSON (released while streaming, never revealing the final
block, linear time for long string arguments); unknown tools, bad arguments and
`"additionalProperties": false`; per-tool timeouts, handler errors and child
control exceptions as tool errors; the round limit (including malformed
rounds), a lower `max_rounds` and `ValueError` below 1; `on_tool` called once
per round (including malformed and unknown calls) with the call and its
result; `confirm` refusal, per-tool `max_calls` and its reset per question,
approval through `ApprovalPort` and the y/N fallback; `timeout=None`
running in-process with no deadline and the extended deadline afterwards;
the final reply after the limit (tool block hidden and `None`, non-tool
block returned); and history rollback on `OperationCancelled`,
`OperationTimedOut`, `LLMError`, `KeyboardInterrupt` (Ctrl+C) and `close()`
mid-question.

```sh
PYTHONPATH=src:tests/helpers .venv/bin/python -m pytest -q tests/unit
```
