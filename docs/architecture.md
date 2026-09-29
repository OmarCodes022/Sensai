# Phase 1 foundation: B1 boundaries (T03 / #16)

The mandatory B1 baseline is the CLI → `ChatSession` → `LLMClient` →
`OllamaClient` stream. `Message` is the frozen, role-tagged wire/history value.
`ChatSession` holds **in-memory** history, starts with one system message, and
sends a copy of the full conversation on every turn. The CLI chooses the model
via argument/configuration. Keep this path working without feature adapters.
The project subject requires incremental CLI output, in-session history, and
clean empty-input/model/connection errors; it does **not** require any optional
memory, tools, RAG, persona switching, or policy feature in B1.

## Data flow and seams

```text
CLI input
  → optional input guardrail → session.send(text)
  → [optional consented profile/facts and retrieval context assembled by caller]
  → B1 ChatSession → LLMStreamPort (OllamaClient) → model chunks
  → optional output guardrail → CLI stream
  → on complete turn only: optional SessionStorePort.save, EventPort.emit

optional tool request → PermissionPort.check → ApprovalPort.request if needed
                      → ToolPort.execute → optional EventPort.emit
```

The bracketed paths are **handoff points**, not implemented features. A caller
may compose `B1SessionAdapter` around `ChatSession` for a read-only history
snapshot and cancellation between chunks, without modifying B1. Never call
`save` from inside a partially consumed generator: full exhaustion is the
success boundary. Storage, embeddings, retrieval, tools, policy, and events
must be independently injected behind the small protocols in
[`port-contracts.md`](port-contracts.md). No dependency on `policy.py` is
required to implement these ports.

| Lane / handoff | Owns | Consumes / returns |
| --- | --- | --- |
| Core chat (Omar, T03–T05) | Typed seams, B1 adapter, fake harness | `Message`, `LLMStreamPort`, `ConversationPort`, `SessionSnapshot` |
| Persona/session/profile/facts (memory lane) | Persona selection, persistence, consent, deletion | `PersonaPort`, `SessionStorePort`, `ProfileStorePort`, `FactStorePort`; no automatic B1 persistence |
| Retrieval (knowledge lane) | Local ingestion/search, source relevance | `EmbeddingPort`, `RetrievalPort` → attributed `RetrievedChunk`; caller decides what enters model context |
| Tools (integration lane) | Execution and resource isolation | `ToolCall` → `ToolResult` **after** permission and any required approval, never as an implicit model side effect |
| Policy/product lane (separately owned) | Rules, scope, consent/approval UX, input/output guardrails | `PermissionPort`, `ApprovalPort`, `GuardrailPort` with typed decisions; deny by default when no applicable authorization |
| Observability/evaluation lane | Safe event consumers | `EventPort` metadata; no automatic prompt/response logging |

## Error, cancellation, privacy invariants

- B1 preserves its `LLMError` hierarchy (including unavailable model and
  connection failures); `ChatSession` removes the pending user message on
  `LLMError`. Empty input is `ValueError` before history mutation. Feature
  adapters use `PortError` for infrastructure failure and `PolicyDenied` for
  an explicitly refused action, not fake assistant replies. Do not retry or
  persist a failed turn silently.
- `OperationCancelled` is distinct from backend failure. `CancellationToken`
  and `B1SessionAdapter` check before dispatch and between chunks; closing the
  adapter iterator or cancelling mid-stream drops the pending user turn from
  *in-memory* history. B1 itself only rolls back `LLMError`, not a partially
  consumed/closed stream. Neither interface preempts a blocked HTTP request or
  retracts already printed chunks. Callers must close abandoned generators and
  avoid persisting/interpreting partial output as a complete turn.
- B1 Ollama defaults to a local URL, but host configuration can point elsewhere;
  *never assume every configured backend is local*. Treat prompts, transcripts,
  facts, profile fields, retrieved text, and tool args/results as private. Do
  not send them to tools/network or include them in events without explicit
  authorization. Policy checks must occur **before** resource access, approval
  before a gated side effect, and output screening before display if enabled.
  Streaming output screening may require buffering; do not claim a post-hoc
  scan prevents earlier chunks from leaking.
- `SessionStorePort` and `ProfileStorePort` expose deletion; `FactStorePort`
  exposes per-profile deletion. Deleting a profile does not implicitly delete
  its facts; the owning lane must coordinate erasure. Persistence, retention,
  encryption, consent, redaction rules, and actual guardrails are **not**
  provided by these ports.
  Fake storage is process-local only. Event fields should contain identifiers,
  statuses, counts, not raw content; enforcement belongs to the caller/policy
  lane. A denial must not call `ToolPort.execute`.

Handoff completion evidence: `tests/unit/test_contracts.py` runs scripted B1
history/stream, a mocked B1 HTTP boundary, cancellation/rollback, port fakes,
and a tiny persisted-chat adapter in the normal pytest runner without services.
