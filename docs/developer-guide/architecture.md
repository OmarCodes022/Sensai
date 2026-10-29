# Architecture

Sensai is one Python package, `sensai`, under `src/sensai/`. The `sensai`
command (`cli/main.py`) builds every object and wires them together; the
other modules do not know about the command line, and `sensai.core` and
`sensai.llm` never import `sensai.chat`, `sensai.cli` or `sensai.settings` at
runtime.

## Layers

| Package | Role |
| --- | --- |
| `sensai.cli` | The `sensai` command: arguments, startup checks, the chat loop (`repl`), raw terminal input, the approval prompt |
| `sensai.chat` | Conversation state: `ChatSession`, personas, system prompt, saved-session recording, the tool-block reader, the `/think` loop (`chat.reasoning`) |
| `sensai.tools`, `sensai.sandbox` | Tool registry and tool loop, `calculate`, `run_python` |
| `sensai.llm` | Ollama HTTP clients and wire format: the streaming chat client and the structured client that runs the `/think` check |
| `sensai.memory` | SQLite storage of sessions and profiles |
| `sensai.core` | Shared types: messages, errors, cancellation token, typed ports, process isolation |
| `sensai.settings` | Settings from the environment and `.env` |
| `sensai.telemetry` | Usage and event hooks; the CLI uses only its operation IDs |

This is how the modules call each other when `sensai` runs (the dotted arrow
is not used by the CLI, which sets no event sink):

```mermaid
flowchart TD
    cli["sensai: cli.main REPL"] --> settings["settings: .env and environment"]
    cli -->|"run_with_tools, /run"| tools["tools: ToolRegistry and tool loop"]
    cli -->|"/think"| reasoning["chat.reasoning: think loop on a scratch session"]
    reasoning -->|"run_with_tools"| tools
    reasoning -->|"check: complete"| structured["llm.structured: OllamaStructuredClient"]
    structured -->|"POST /api/chat, format"| server
    tools -->|"session.send"| session["chat.session: ChatSession"]
    cli -->|"create_client"| ollama["llm.ollama: OllamaClient"]
    session -->|"client.stream"| ollama
    ollama -->|"token given: ControlledLLMClient"| isolation["core.isolation: spawned child process"]
    isolation -->|"POST /api/chat"| server[("Ollama server")]
    tools -->|"confirm=True: request"| approval["cli.approval: TerminalApproval"]
    tools -->|"timed tool: ControlledTool"| isolation
    isolation -->|"python_tool"| sandbox["sandbox: run_python"]
    cli -->|"after_turn"| recorder["chat.saved_sessions: SessionRecorder"]
    recorder -->|"generate_title"| ollama
    recorder -->|"save, set_title"| memory[("memory.sqlite_store: SQLite file")]
    cli -->|"list, load, save profile"| memory
    isolation -->|"new_operation_id"| telemetry["telemetry: usage and event hooks"]
    ollama -.->|"event_sink only"| telemetry
```

## One turn

`repl()` handles commands itself; any other line starts a turn. The CLI
creates a `CancellationToken` and prints every chunk `run_with_tools()`
yields. `run_with_tools()` calls `ChatSession.send()`, which appends the user
message and streams `client.stream(model, messages)`. A `BlockReader` holds
back a final JSON block; a tool call runs through the registry and its result
goes back as the next user message, for up to five rounds. A completed turn
ends with `SessionRecorder.after_turn()`, which saves the session. Here the
model asks for `run_python`, a `confirm=True` tool, then answers with its
result:

```mermaid
sequenceDiagram
    actor User
    participant CLI as cli.main repl
    participant ToolLoop as tools.run_with_tools
    participant Session as ChatSession
    participant Model as OllamaClient and model
    participant Registry as ToolRegistry
    participant Approval as TerminalApproval
    participant Sandbox as run_python in a child process
    User->>CLI: question
    CLI->>ToolLoop: run_with_tools(session, registry, text, token)
    ToolLoop->>Session: send(text)
    Session->>Model: stream(model, messages)
    Model-->>Session: reply chunks
    Session-->>ToolLoop: chunks ending with a tool block
    Note over ToolLoop: BlockReader hides the tool block
    ToolLoop->>Registry: execute(ToolCall run_python)
    Registry->>Approval: request(ApprovalRequest)
    Approval->>User: Run run_python? with a code preview
    User-->>Approval: y, n or v
    Approval-->>Registry: ApprovalDecision
    alt approved
        Registry->>Sandbox: python_tool through ControlledTool
        Sandbox-->>Registry: ToolResult with exit code, stdout, stderr
    else refused
        Note over Registry: error result, tool approval refused
    end
    Registry-->>ToolLoop: ToolResult
    ToolLoop->>CLI: on_tool(call, result) prints the Using tool line
    ToolLoop->>Session: send(Tool result or Tool error from run_python)
    Session->>Model: stream(model, messages)
    Model-->>Session: reply chunks
    Session-->>ToolLoop: answer chunks, no tool block
    ToolLoop-->>CLI: visible text
    CLI-->>User: streamed answer
```

## Cancellation and deadlines

A `CancellationToken` (`core/cancellation.py`) holds one absolute
`time.monotonic()` deadline and an optional callback. For each turn the CLI
sets the deadline to `--operation-timeout` seconds and passes
`TerminalInput.cancel_requested`, which reports a Ctrl+C or a lone Esc typed
during the reply. `raise_if_cancelled()` raises `OperationCancelled` or
`OperationTimedOut`; the CLI prints `Réponse interrompue` or
`Délai maximal dépassé`. In the main process, the session, the tool loop and
the registry check this token. Approval prompts and tools registered with
`timeout=None` pause its deadline.

A child process never gets that token. It builds a fresh one with the
deadline only and no callback (`_child()` in `core/isolation.py`). For a timed
tool, that deadline is the earlier of the tool's timeout and the question
deadline (`ToolRegistry.execute()` in `tools.py`). The parent keeps checking
the question token, and on Ctrl+C or Esc it sends SIGTERM to the child's
process group. A timed handler, `run_python` included, therefore sees the
deadline through `raise_if_cancelled()`, never Ctrl+C.

When a turn fails or is cancelled, `ChatSession.send()` and `run_with_tools()`
delete every message the turn added, tool rounds included. Only completed
turns stay in history and get saved. Text already printed stays on screen.

## Process isolation

`core/isolation.py` runs work in a fresh `spawn` child process that leads its
own session and process group. `ControlledLLMClient` runs each model request
this way (`OllamaClient.stream()` uses it whenever it gets a token, which the
CLI always passes), and `ControlledTool` runs each tool registered with a
numeric timeout. The parent checks the token and polls a socket pair at least
every 20 ms; the child sends chunks, results and typed errors as
newline-delimited JSON. To stop a child, the parent sends SIGTERM to its
group, waits 200 ms, sends SIGKILL and reaps it. Factories and handlers cross
the process boundary, so they must be importable and pickleable.

The sandbox adds its own layer: `run_python()` runs `sys.executable -I main.py`
in a new temporary folder and its own process group, with `setrlimit` limits
on CPU, memory, file size and core dumps, an almost empty environment and no
stdin. On Linux the code dies with its parent. A SIGTERM handler lets the
worker kill the code and delete the folder first, and each run removes folders
left by dead processes.

## Design choices

- We call Ollama's HTTP API directly with `requests` instead of an LLM
  framework, because the subject forbids LLM frameworks and requires direct
  Ollama HTTP calls.
- We run model requests and timed tools in a child process instead of the
  main process, because killing a process group is how Sensai interrupts
  blocked work on Ctrl+C or at the deadline.
- We commit a turn to history only when its stream completes, instead of
  keeping partial replies, so a cancelled or failed turn is never sent back as
  context or saved.
- After a persona switch, each request repeats the system message before the
  newest user message, instead of relying on the first message alone, because
  older assistant introductions must not undo the active role.
- The sandboxed code gets its own process group instead of sharing the tool
  worker's, so the sandbox's 15 s limit can kill the code without killing the
  worker or Sensai.
