# Architecture overview

The base chat (B1 in the subject catalogue) is the CLI → `ChatSession` →
`LLMClient` → `OllamaClient` stream. `Message` is the frozen, role-tagged
wire/history value. `ChatSession` holds **in-memory** history, starts with one
system message, and sends a copy of the full conversation on every turn. The
CLI chooses the model via argument/configuration. The subject requires
incremental CLI output, in-session history, and clean empty-input/model/
connection errors; it does **not** require any optional feature in the base
chat. Keep this path working without feature adapters.

The CLI also implements two optional features on top of it:

- **Personas** (`sensai.chat.personas`): the shared prompt plus a selected
  persona block forms the system message; `/persona <id>` replaces it between
  turns while keeping completed exchanges. See
  [the persona guide](../product/personas.md).
- **Saved sessions and creator profile** (`sensai.chat.saved_sessions` and
  `sensai.memory.sqlite_store`): completed turns are saved to SQLite and can be
  resumed; a stored creator profile is injected into the system message. See
  [storage.md](storage.md).

## Module layout and dependencies

| Package | Responsibility |
| --- | --- |
| `sensai.cli` | Entry points: `main` (`sensai`: arguments, REPL), `remote` (`sensai-remote`: SSH tunnel), `terminal` (POSIX input with cancel keys) |
| `sensai.chat` | Chat session history, personas, system prompt (packaged `system_prompt.txt`), saved-session recording (`saved_sessions`) |
| `sensai.settings` | Configuration from the environment and `.env` |
| `sensai.core` | Messages, errors, cancellation token, typed ports (`ports.py`), process isolation (`isolation.py`), declarative policy types |
| `sensai.llm` | Ollama HTTP clients: streaming chat, embeddings, structured (JSON-schema) replies |
| `sensai.memory` | SQLite storage (`sqlite_store`) and the in-memory vector index |
| `sensai.telemetry` | Optional usage and privacy-safe event hooks |

`sensai.core` and `sensai.llm` do not import `sensai.chat`, `sensai.cli` or
`sensai.settings` at runtime
(`ChatSessionAdapter` refers to `ChatSession` and `create_client` to
`Settings` only for type checking). `core.isolation` uses `llm.client`/`llm.ollama_api`, and
`llm.ollama` imports `core.isolation` lazily when a cancellation token is
passed; that runtime link is intentional.

This is how the modules call each other when `sensai` or `sensai-remote` runs
(the dotted arrow is not used by the CLI, which sets no event sink):

```mermaid
flowchart TD
    remote["sensai-remote: cli.remote"] -->|"SSH tunnel, then run_chat"| cli["sensai: cli.main REPL"]
    remote --> settings["settings: .env and environment"]
    cli --> settings
    cli -->|"run_with_tools, /run"| tools["tools: ToolRegistry and tool loop"]
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

## Data flow and extension points

```text
CLI input
  → optional input guardrail → session.send(text)
  → [optional consented profile/facts and retrieval context assembled by caller]
  → ChatSession → LLMStreamPort (OllamaClient) → model chunks
  → optional output guardrail → CLI stream
  → on complete turn only: SessionStorePort.save (CLI session recorder), optional EventPort.emit

optional tool request → PermissionPort.check → ApprovalPort.request if needed
                      → ToolPort.execute → optional EventPort.emit
```

Guardrails, retrieval context, tools, permissions, approvals and events are
**extension points**, not implemented features. A caller may compose
`ChatSessionAdapter` around `ChatSession` for a read-only history snapshot and
propagation of cancellation/deadlines. Never call `save` from inside a
partially consumed generator: full exhaustion is the success boundary.
Storage, embeddings, retrieval, tools, policy, and events must be
independently injected behind the small protocols in
[`ports.md`](ports.md). No dependency on `policy.py` is
required to implement these ports.

| Area | Owns | Consumes / returns |
| --- | --- | --- |
| Base chat | Typed seams, base-chat adapter, fake harness | `Message`, `LLMStreamPort`, `ConversationPort`, `SessionSnapshot` |
| Personas, sessions, profiles, facts | Persona selection, persistence, consent, deletion | `PersonaPort`, `SessionStorePort`, `ProfileStorePort`, `FactStorePort`; the CLI saves completed turns only |
| Retrieval | Local ingestion/search, source relevance | `EmbeddingPort`, `RetrievalPort` → attributed `RetrievedChunk`; caller decides what enters model context |
| Tools | Execution and resource isolation | `ToolCall` → `ToolResult` **after** permission and any required approval, never as an implicit model side effect |
| Policy | Rules, scope, consent/approval UX, input/output guardrails | `PermissionPort`, `ApprovalPort`, `GuardrailPort` with typed decisions; deny by default when no applicable authorization |
| Observability and evaluation | Safe event consumers | `EventPort` metadata; no automatic prompt/response logging |

## One turn with a tool call

This is one question in the CLI where the model asks for `run_python`, a
`confirm=True` tool, and then answers with its result:

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

## Error, cancellation, privacy invariants

- The base chat preserves the `LLMError` hierarchy and empty-input validation.
  `ChatSession` removes all incomplete turns on errors, cancellation, timeout
  or early close; only successful exhaustion commits an assistant reply.
  Feature failures remain `PortError`, with `PolicyDenied` for denied policy
  decisions.
- `OperationCancelled` and `OperationTimedOut` are distinct. The same optional
  token travels through adapters without resetting its monotonic deadline.
  Token-bearing Ollama calls run in an interruptible process group, which is
  stopped and reaped on abandonment. Previously displayed text is retained;
  partial turns must not be persisted. See [cancellation.md](cancellation.md).
- Ollama defaults to a local URL, but host configuration can point elsewhere;
  *never assume every configured backend is local*. Treat prompts, transcripts,
  facts, profile fields, retrieved text, and tool args/results as private. Do
  not send them to tools/network or include them in events without explicit
  authorization. Policy checks must occur **before** resource access, approval
  before a gated side effect, and output screening before display if enabled.
  Streaming output screening may require buffering; do not claim a post-hoc
  scan prevents earlier chunks from leaking.
- `SessionStorePort` and `ProfileStorePort` expose deletion; `FactStorePort`
  exposes per-profile deletion. The ports do not require deleting a profile's
  facts with it; the SQLite adapter does so atomically, other adapters must
  coordinate erasure themselves. Retention, encryption, consent, redaction
  rules, and actual guardrails are **not** provided by these ports.
  Fake storage is process-local only. Event fields should contain identifiers,
  statuses, counts, not raw content; enforcement belongs to the caller or
  policy layer. A denial must not call `ToolPort.execute`.

`tests/unit/core/test_ports.py` runs scripted base-chat history/stream, a
mocked Ollama HTTP boundary, cancellation/rollback, port fakes, and a tiny
persisted-chat adapter in the normal pytest runner without services.
