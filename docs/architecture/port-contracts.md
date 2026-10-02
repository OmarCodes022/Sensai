# Phase 1 typed ports (T04 / #17, T05 / #18)

`src/sensai/core/contracts.py` is a dependency-free-of-features module (uses only
B1 code and the Python standard library). Protocols are structurally typed;
`@runtime_checkable` checks member presence, **not** parameter/return types.
`Message` is the existing frozen Pydantic B1 message (system/user/assistant),
not a replacement wire format. Dataclasses are frozen values; mapping fields
are typed but not deep-frozen, so adapters must copy untrusted mutable input
when retaining it.

| Boundary | Call(s) and value types | Required behavior / lane |
| --- | --- | --- |
| Model and conversation | `LLMStreamPort.stream(model, Sequence[Message]) -> Iterator[str]`; `ConversationPort.send(text) -> Iterator[str]` | `OllamaClient` and `ChatSession` already satisfy these. Chunks must remain ordered; do not merge until the caller wants a completed reply. |
| B1 bridge | `B1SessionAdapter(ChatSession).history -> tuple[Message, ...]`, `.send(text, cancellation=None) -> Iterator[str]` | History is a snapshot; no B1 file edits. Only a completed stream commits the assistant message; incomplete adapter turns are removed from in-memory B1 history. |
| Persona | `Persona(id, system_prompt)`; `PersonaPort.get(id) -> Persona \| None` | Config/selection lane owns prompt loading and persona switching. B1 can use `system_prompt` at construction; switching without clearing history is future work. |
| Session | `SessionSnapshot(id, messages: tuple[Message, ...], persona_id=None)`; `SessionStorePort.load/save/delete` | Memory lane persists **completed** snapshots; missing is `None`. Does not alter B1 history or imply disk storage. |
| Profile | `Profile(id, preferences: Mapping[str, str])`; `ProfileStorePort.load/save/delete` | Memory/privacy lane injects preferences only when permitted; missing is `None`. |
| Facts | `Fact(id, text, source)`; `FactStorePort.list_for(profile_id)/upsert(profile_id, fact)/delete(profile_id, fact_id)` | Memory lane scopes facts by profile and honors deletion; `source` carries provenance. |
| Knowledge | `EmbeddingPort.embed(text) -> Sequence[float]`; `RetrievalPort.search(query, limit) -> Sequence[RetrievedChunk]` | Retrieval lane returns `RetrievedChunk(id, text, source, score)`; selection/context assembly is caller-owned. |
| Tools | `ToolPort.execute(ToolCall(name, arguments: Mapping[str, str])) -> ToolResult(output)` | Tool lane executes only after caller-enforced authorization; this simple text envelope is **not** an MCP implementation. |
| Policy | `PermissionPort.check(PermissionRequest(action, resource)) -> PermissionDecision(allowed, reason)`; `ApprovalPort.request(ApprovalRequest(action, resource, reason)) -> ApprovalDecision(approved)`; `GuardrailPort.inspect(text, "input" \| "output") -> GuardrailDecision(allowed, text=None, reason="")` | Product/policy lane owns decisions and UX. A blocked decision does not itself execute or expose content; `text` may supply an allowed redacted replacement. Caller must use the replacement, or original text only if allowed. |
| Events | `EventPort.emit(Event(name, fields: Mapping[str, str]))` | Telemetry lane sees explicitly supplied metadata only; caller excludes raw messages, personal data, arguments, and results. |

`LLMError` (B1) is still the model error. `PortError` denotes feature-adapter
failure; `PolicyDenied(PortError)` is available if a caller needs an exception
instead of a denied decision. `OperationCancelled(SensaiError)` and
`CancellationToken.cancel()/raise_if_cancelled()` describe cooperative
cancellation; neither modifies transport APIs or guarantees an interrupted
Ollama request. Never treat cancellation as a successful saved turn.

`tests/helpers/fakes.py` supplies deterministic `FakeOllama` (scripted ordered chunks,
model/message call recording), `FakeStorage` (isolated persona/session/profile/
fact views), `FakeEmbedding`, `FakeRetrieval`, `FakeTool`, and `FakeEventSink`.
The existing `FakeClient` remains usable by B1 tests. Reusable port assertions
and a minimal persistence adapter are in `tests/unit/core/test_contracts.py`; run
with `python -m pytest -q tests/unit/core/test_contracts.py tests/unit/app/test_session.py
tests/unit/llm/test_ollama_client.py` in the project environment. No live Ollama,
database, embeddings service, or tool execution is needed.
