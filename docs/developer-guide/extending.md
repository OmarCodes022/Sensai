# Extending

The two most common extensions are a new tool and a new built-in persona.
Neither needs a change to the chat loop.

## How the model calls a tool

The CLI appends `tool_instructions()` (`src/sensai/tools.py`) to the system
prompt: the tools as JSON (name, description, parameters) and how to call
them. To use a tool, the model ends its reply with one JSON object at column
zero, on its own line:

```text
I'll calculate that.
{"tool": "calculate", "arguments": {"expression": "(14 + 6) / 100"}}
```

`BlockReader` (`src/sensai/chat/blocks.py`) holds back a line that starts
with `{` while it can still become that final object, so the user never sees
it. `run_with_tools()` parses it, runs it through `ToolRegistry.execute()` and
sends the result as the next user message, starting with
`Tool result from <name>:` or `Tool error from <name>:`. A question allows
five rounds (`MAX_TOOL_CALLS`); the last result also asks for a final answer
without tools. A final object without a `"tool"` key ends the loop and is
returned to the caller.

## Add a tool

Define the tool and its handler in an importable module:

```python
from sensai.core.ports import ToolDefinition, ToolResult

WORD_COUNT = ToolDefinition(
    "word_count", "Count the words of a text.",
    {"type": "object", "properties": {"text": {"type": "string"}},
     "required": ["text"], "additionalProperties": False},
)


def word_count(arguments, cancellation=None):
    return ToolResult(str(len(arguments["text"].split())))
```

`parameters` is a JSON-schema subset. Before approval and before the handler
runs, the registry checks `required`, the basic `type` of each listed property
(`string`, `number`, `integer`, `boolean`, `array`, `object`, `null`) and,
only with `"additionalProperties": false`, that no other argument is present.
A handler takes `(arguments, cancellation)` and returns
`ToolResult(output, error=None)`; set `error` to report a failure to the model.
An exception in the handler also becomes an error result.

Then register it where the CLI builds its registry, in `_tools()` in
`src/sensai/cli/main.py`:

```python
def _tools(read, approval=None, data_dir=None):
    registry = ToolRegistry(approval, read=read)
    registry.register(CALCULATE, calculate)
    registry.register(RUN_PYTHON, partial(python_tool, data_dir=data_dir), confirm=True)
    registry.register(WORD_COUNT, word_count)  # the new tool
    return registry
```

`register(definition, handler, *, timeout=30.0, confirm=False, max_calls=None)`
takes three settings:

| Setting | Effect |
| --- | --- |
| `timeout` | Seconds per call, counted after approval. A number runs the handler in a fresh spawned process (`ControlledTool`), so it must be pickleable (a module-level function, or a `partial` of one) and open its own files or connections. `None` runs it in the main process without a limit, for tools that read the terminal or need in-memory state; the question deadline pauses meanwhile. |
| `confirm` | `True` asks the user before each call through `TerminalApproval`. A refusal returns the error `tool approval refused`. |
| `max_calls` | Limit of calls to this tool per question; `0` disables it. |

The new tool then shows in `/tools` and in the model's instructions. Test it
like `tests/unit/core/test_tools.py`; handlers used in spawned-process tests
live in `tests/helpers/tool_handlers.py`.

## Add a built-in persona

Add an entry to `src/sensai/chat/personas.json` with exactly `id`, `name`,
`tone`, `role` and `response_scope`, all non-empty strings. The built-ins are
written in French:

```json
{
  "id": "edition",
  "name": "Édition",
  "tone": "Précis et bienveillant.",
  "role": "Aider Nadia à relire ses brouillons de légendes avant validation humaine.",
  "response_scope": "Propose des corrections sans inventer de faits. Les posts relèvent de Rédaction (redaction) ; les réponses à la communauté relèvent de Communauté (communaute) ; les rapports relèvent d'Analyse (analyse)."
}
```

`PersonaRegistry` (`src/sensai/chat/personas.py`) turns each entry into the
persona's instructions: the role, tone and scope, plus shared rules on
switching persona and on the response language. The file ships with the
package, so `--list-personas` and `/persona` show the new entry at the next
start.

`tests/unit/chat/test_personas.py` checks that each built-in scope names every
other built-in ID in parentheses, such as `(analyse)`: add the new ID to the
other entries' `response_scope` too. That file and
`tests/unit/cli/test_personas.py` also check the exact list of built-ins.

## Design choices

- We use a text protocol, one JSON object at the end of the reply, instead of
  Ollama's native tool calling, because `gemma3:1b`, the model used in the
  examples, has no native tool calling: Ollama lists its only capability as
  `completion`.
- We send tool results back as user messages prefixed `Tool result from` or
  `Tool error from` instead of adding a new role, so the saved message schema
  stays unchanged.
- We give tools a 30 s timeout by default and run timed tools in their own
  process instead of the chat process, so a stuck tool gives an error result
  instead of blocking the chat.
- We register `run_python` with `confirm=True` instead of running it
  directly, so Sensai always asks before running code the model wrote.
- We keep personas in a JSON catalogue instead of Python code, because a
  persona must be configurable without changing the code.
