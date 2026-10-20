# Task brief: tool loop (not implemented)

This is a work brief for T18, "Let Sensai call tools and use their results".
**None of it is implemented yet**: the files below hold typed contracts and
placeholders whose bodies raise `NotImplementedError("T18: …")`.

Goal: let the model ask for a tool, run it safely, give it the result and let
it answer, without native tool calling (the default model, `gemma3:1b`, has
none).

## Block format

The model ends its reply with one JSON object on its own lines:

````text
I'll check the file first.
{"tool": "read_file", "arguments": {"path": "/work/notes.md"}}
````

- Only a block at the very end of the reply counts; whitespace after it is
  allowed. Any other text after it makes it normal text.
- A block that is not a valid JSON object is shown as normal text; no tool
  runs.
- A tool block has a `"tool"` key. `arguments` is an object of JSON values;
  missing means `{}`.
- A valid block without a `"tool"` key is not a tool call; see "Other
  blocks".

The CLI streams replies, so the reader holds back output from a line starting
with `{` until it knows whether that line starts the final block. The user
never sees the raw block.

## Contracts

`src/sensai/core/ports.py` (existing callers keep working):

- `ToolDefinition(name, description, parameters={})`: a tool as shown to the
  model. `parameters` is a JSON-schema subset,
  `{"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}`,
  used both for argument checks and by `tool_instructions`. Not hashable when
  `parameters` is a dict.
- `ToolCall(name, arguments: Mapping[str, object])`: arguments are JSON values.
- `ToolResult(output, error=None)`: `error` is set when the call failed.
- `ToolPort.execute(call, cancellation=None) -> ToolResult`: unchanged.

`src/sensai/chat/blocks.py` (implemented by T18; reusable by other
block-based features):

- `BlockReader.feed(chunk) -> str`: text safe to print now.
- `BlockReader.finish() -> tuple[str, dict | None]`: the full visible text
  (not just the remainder) and the parsed block, or `None`. The caller prints
  only the part not yet returned by `feed`.
- `split_block(reply)`: the same, for a complete reply.

`src/sensai/tools.py`:

- `MAX_TOOL_CALLS = 5`, `TOOL_TIMEOUT_SECONDS = 30.0`.
- `ToolHandler = Callable[[Mapping[str, object], CancellationToken | None], ToolResult]`.
- `ToolRegistry(approval: ApprovalPort | None = None)`:
  `register(definition, handler, *, timeout=TOOL_TIMEOUT_SECONDS,
  confirm=False, max_calls=None)` (duplicate name raises `ValueError`; see
  "Registering tools"), `definitions()`, `execute(call, cancellation=None)`;
  it satisfies `ToolPort`. `ToolRegistry()` must keep working.
- `tool_instructions(definitions) -> str`: text appended to the system prompt
  listing each tool (name, description, parameters) and the block format.
- `parse_tool_call(block) -> ToolCall`: raises `ValueError` on a malformed block.
- `run_with_tools(session, registry, text, cancellation=None)
  -> Generator[str, None, tuple[str, dict | None]]`: the loop; yields visible
  text and returns the last reply's visible text and its non-tool block (or
  `None`). Trims history whenever the turn does not complete.

## Behaviour to build

1. Send the user's message; stream the reply through `BlockReader`, yielding
   visible text.
2. No block, or a block without `"tool"`: the loop ends (see below).
3. Tool block: one round. Parse it and `registry.execute(call)`; a malformed
   call (`parse_tool_call` fails) or unknown tool gives an error result. Send
   the result back to the model, clearly marked as a tool result, and read
   the next reply.
4. **Every round counts toward `MAX_TOOL_CALLS`**, including malformed blocks
   and unknown tools, so the model cannot loop forever.
5. After `MAX_TOOL_CALLS` rounds, send a last message asking for a final
   answer without tools. If that reply ends with a tool block, the block is
   hidden, not executed, and the return value is `(visible, None)`; a
   non-tool block is returned unchanged.

`ToolRegistry.execute` returns a `ToolResult`:

- Unknown tool → error result, not an exception.
- Arguments checked against `parameters` (`required` names present,
  `properties` basic JSON types) → error result when invalid.
- Exceeding the tool's `timeout` → error result.
- Refused `confirm` or exceeded `max_calls` → error result; the handler does
  not run.
- Handler `Exception` subclasses → error result with a short message. Tool
  errors never crash the chat. Other `BaseException`s (`KeyboardInterrupt`,
  ...) are not swallowed.
- `OperationCancelled` (user cancellation) and `OperationTimedOut` (the
  question's overall deadline on the token) **propagate**; they are not
  tool results.

Turn history: `ChatSession.send` saves every finished round in
`session.messages`. `run_with_tools` records its length before the turn and,
**whenever the turn does not complete**, trims it back to that length and
re-raises. This covers any exception (`OperationCancelled`,
`OperationTimedOut`, `LLMError`, `KeyboardInterrupt`, ...) and `close()` /
`GeneratorExit`: Ctrl+C in the CLI arrives as `KeyboardInterrupt`, then
`stream.close()` (`src/sensai/cli/main.py`). Use a `completed` flag like
`ChatSession.send` (`src/sensai/chat/session.py`), so an interrupted turn
leaves no partial rounds.

Existing `ControlledTool` (`src/sensai/core/isolation.py`) satisfies
`ToolPort` and can interrupt a blocked handler, but today it forwards only
`output`, not `error`.

## Registering tools

`register` takes three per-tool settings:

- `timeout` (default `TOOL_TIMEOUT_SECONDS`): seconds per call. A number runs
  the handler with that limit; isolating it (e.g. `ControlledTool`, which runs
  the tool in a child process) is the implementer's choice. `None` means no
  limit and the handler runs **in the main process**. Use `None` for
  interactive tools that read the terminal, since child processes cannot.
- `confirm` (default `False`): ask before each call. With
  `ToolRegistry(approval=...)`, send an `ApprovalRequest(action, resource,
  reason)` to that `ApprovalPort` and run only if `ApprovalDecision.approved`
  (T46 will provide a terminal-backed one). Without it, use a plain y/N
  prompt on the chat's terminal reader; how the registry reaches the reader
  is the implementer's choice. A refusal is an error result; the handler
  does not run.
- `max_calls` (default `None`): limit for this tool per question. Calls
  beyond it are error results, and every call also counts toward
  `MAX_TOOL_CALLS`. `run_with_tools` resets the counts at the start of each
  question; the method for it (e.g. `start_question()`) is the
  implementer's choice.

```python
registry.register(RUN_PYTHON, run_python, confirm=True)   # T19
registry.register(ASK_USER, ask_user, timeout=None)       # T28
```

Interactive tools such as `ask_user` handle Ctrl+C themselves: the handler
catches `KeyboardInterrupt` while reading and returns a result such as
`ToolResult("user skipped the question")`, so the turn continues instead of
being cancelled. Ctrl+C outside such a handler still cancels the turn.
Interactive handlers must not poll the chat's `cancel_requested` callback
(directly or through the token's `raise_if_cancelled()`) while the user
types: it discards unrecognised pending keys (`src/sensai/cli/terminal.py`).

Time spent waiting for the user does not count toward the question's overall
deadline. A `timeout=None` handler (and `execute` around it) receives a token
that keeps the cancel check but has **no deadline**. After it returns, the
rest of the turn uses the deadline extended by the time the tool took (for
example a new `CancellationToken` with the same cancel check).

## Other blocks

`run_with_tools` executes only blocks that have a `"tool"` key. Any other
valid block ends the loop and is returned to the caller unchanged:

```python
visible, block = yield from run_with_tools(session, registry, text)
if block is not None:
    ...  # handled by the caller
```

## How later tasks plug in

Each registers a `ToolDefinition` and a handler; none of them changes the loop.

- T19: `run_python` (sandboxed code execution).
- T41: `web_search`.
- T28: `ask_user` (ask the user a question).
- T26: `read_file` / `write_file` / `create_file`, backed by `FileSystemPort`
  ([filesystem brief](filesystem-permissions.md)); permission checks stay in
  the handler.
- T42: MCP tools, each mapped to a `ToolDefinition`.
- T21 (self-fixing code) and T20 (reasoning loop with tools) call
  `run_with_tools`.

## Tests

Use fake sessions and handlers; no live model or network. Cover streamed
blocks split across chunks, invalid, non-final and non-tool blocks, unknown
tools, bad arguments, per-tool timeouts, handler errors, the round limit
(including malformed rounds), `confirm` refusal, per-tool `max_calls` and
its reset per question, approval through `ApprovalPort` and the y/N
fallback, `timeout=None` running in-process with no deadline and the
extended deadline afterwards, the final reply after the limit (tool block
hidden and `None`, non-tool block returned), and history trimming on
`OperationCancelled`, `OperationTimedOut`, `LLMError`, `KeyboardInterrupt`
(Ctrl+C) and `close()` mid-turn.

```sh
.venv/bin/python -m pytest -q tests/unit
```

Contract examples are in `tests/unit/core/test_tool_ports.py`; they do not test
a working loop.
