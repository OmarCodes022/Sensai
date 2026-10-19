# Typed ports and test doubles

`src/sensai/core/ports.py` depends only on the core message, error and
cancellation types and the Python standard library (application types are
referenced for type checking only). Protocols are structurally typed;
`@runtime_checkable` checks member presence, **not** parameter/return types.
`Message` is the existing frozen Pydantic chat message (system/user/assistant),
not a replacement wire format. Dataclasses are frozen values; mapping fields
are typed but not deep-frozen, so adapters must copy untrusted mutable input
when retaining it.

| Boundary | Call(s) and value types | Required behavior |
| --- | --- | --- |
| Model and conversation | `LLMStreamPort.stream(model, Sequence[Message], cancellation=None) -> Iterator[str]`; `ConversationPort.send(text, cancellation=None) -> Iterator[str]` | `OllamaClient` and `ChatSession` already satisfy these. Chunks must remain ordered; do not merge until the caller wants a completed reply. |
| Base-chat bridge | `ChatSessionAdapter(ChatSession).history -> tuple[Message, ...]`, `.send(text, cancellation=None) -> Iterator[str]` | History is a snapshot. Only a completed stream commits the assistant message; incomplete adapter turns are removed from in-memory history. |
| Persona | `Persona(id, system_prompt)`; `PersonaPort.get(id) -> Persona \| None` | `PersonaRegistry` validates built-in/custom profiles for startup and between-turn selection. The CLI combines the shared prompt with the selected persona; `/persona <id>` replaces the system message while preserving completed conversation history. |
| Session | `SessionSnapshot(id, messages: tuple[Message, ...], persona_id=None)`; `SessionStorePort.load/save/delete` | Persist **completed** snapshots only; missing is `None`. The port does not alter chat history or imply disk storage; the SQLite adapter and the CLI session recorder are described in [storage.md](storage.md). |
| Profile | `Profile(id, preferences: Mapping[str, str])`; `ProfileStorePort.load/save/delete` | Inject preferences only when permitted; missing is `None`. The CLI injects the stored creator profile into the system message. |
| Facts | `Fact(id, text, source)`; `FactStorePort.list_for(profile_id)/upsert(profile_id, fact)/delete(profile_id, fact_id)` | Scope facts by profile and honor deletion; `source` carries provenance. |
| Knowledge | `EmbeddingPort.embed(text) -> Sequence[float]`; `RetrievalPort.search(query, limit) -> Sequence[RetrievedChunk]` | Return `RetrievedChunk(id, text, source, score)`; selection/context assembly is caller-owned. |
| Tools | `ToolPort.execute(ToolCall(name, arguments: Mapping[str, str]), cancellation=None) -> ToolResult(output)` | Execute only after caller-enforced authorization; this simple text envelope is **not** an MCP implementation. |
| Policy | `PermissionPort.check(PermissionRequest(action, resource)) -> PermissionDecision(allowed, reason)`; `ApprovalPort.request(ApprovalRequest(action, resource, reason)) -> ApprovalDecision(approved)`; `GuardrailPort.inspect(text, "input" \| "output") -> GuardrailDecision(allowed, text=None, reason="")` | The policy layer owns decisions and UX. A blocked decision does not itself execute or expose content; `text` may supply an allowed redacted replacement. Caller must use the replacement, or original text only if allowed. |
| Filesystem | `FileAction`; `FileAccessRule(path, actions, recursive=False)`; `FileSystemPort.creator_id`, `.read_text/.write_text/.create_text` | Contract only: creator-bound UTF-8 regular files, per-operation authorization and no symlinks. The [task brief](../tasks/filesystem-permissions.md) defines required enforcement and tests; no implementation yet. |
| Events | `EventPort.emit(Event(name, fields: Mapping[str, str]))` | Event consumers see explicitly supplied metadata only; caller excludes raw messages, personal data, arguments, and results. |

`LLMError` is still the model error. `PortError` denotes feature-adapter
failure; `PolicyDenied(PortError)` is available if a caller needs an exception
instead of a denied decision. `OperationCancelled(SensaiError)` and
`CancellationToken.cancel()/raise_if_cancelled()` share an absolute monotonic
deadline. `OperationTimedOut` distinguishes total deadline expiry. Token-bearing
Ollama calls and `ControlledTool` use process isolation to interrupt blocked
work; direct calls without a token remain valid. Never save an abandoned turn.
See [cancellation.md](cancellation.md) for execution and terminal guarantees.

`tests/helpers/fakes.py` supplies deterministic `FakeOllama` (scripted ordered chunks,
model/message call recording), `FakeStorage` (isolated persona/session/profile/
fact views), `FakeEmbedding`, `FakeRetrieval`, `FakeTool`, and `FakeEventSink`.
`FakeClient` is the scripted chat client used across the unit tests, and
`scripted_terminal()` replaces `TerminalInput` in CLI tests. Reusable port
assertions are in `tests/helpers/port_assertions.py`; a minimal persistence
adapter and the fake-port checks are in `tests/unit/core/test_ports.py`. Run
with `python -m pytest -q tests/unit/core/test_ports.py tests/unit/chat/test_session.py
tests/unit/llm/test_ollama_client.py` in the project environment. No live Ollama,
database, embeddings service, or tool execution is needed.
