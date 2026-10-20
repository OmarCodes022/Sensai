"""Small, backend-independent boundaries for features built around the base chat (B1)."""

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

from sensai.core.errors import SensaiError
from sensai.core.cancellation import CancellationToken, OperationCancelled, OperationTimedOut
from sensai.core.messages import Message

if TYPE_CHECKING:
    from sensai.chat.session import ChatSession


class PortError(SensaiError):
    """A feature adapter failed; B1 model failures still raise LLMError."""


class PolicyDenied(PortError):
    """A caller chose to surface a denied policy decision as an error."""


@runtime_checkable
class LLMStreamPort(Protocol):
    def stream(self, model: str, messages: Sequence[Message],
               cancellation: CancellationToken | None = None) -> Iterator[str]: ...


@runtime_checkable
class ConversationPort(Protocol):
    def send(self, text: str, cancellation: CancellationToken | None = None) -> Iterator[str]: ...


class ChatSessionAdapter:
    """Expose B1 history and roll back an interrupted in-memory turn.

    Consumption is single-threaded, as with ChatSession. The backend owns
    interrupting blocked requests; the session owns complete-turn history.
    """

    def __init__(self, session: "ChatSession"):
        self.session = session

    @property
    def history(self) -> tuple[Message, ...]:
        return tuple(self.session.messages)

    def send(
        self, text: str, cancellation: CancellationToken | None = None
    ) -> Iterator[str]:
        yield from self.session.send(text, cancellation)


@dataclass(frozen=True)
class Persona:
    id: str
    system_prompt: str


@runtime_checkable
class PersonaPort(Protocol):
    def get(self, persona_id: str) -> Persona | None: ...


@dataclass(frozen=True)
class SessionSnapshot:
    id: str
    messages: tuple[Message, ...]
    persona_id: str | None = None


@dataclass(frozen=True)
class SessionSummary:
    id: str
    title: str | None
    created_at: str
    updated_at: str


@runtime_checkable
class SessionStorePort(Protocol):
    def load(self, session_id: str) -> SessionSnapshot | None: ...

    def save(self, session: SessionSnapshot) -> None: ...

    def delete(self, session_id: str) -> None: ...


@dataclass(frozen=True)
class Profile:
    id: str
    preferences: Mapping[str, str]


@runtime_checkable
class ProfileStorePort(Protocol):
    def load(self, profile_id: str) -> Profile | None: ...

    def save(self, profile: Profile) -> None: ...

    def delete(self, profile_id: str) -> None: ...


@dataclass(frozen=True)
class Fact:
    id: str
    text: str
    source: str


@runtime_checkable
class FactStorePort(Protocol):
    def list_for(self, profile_id: str) -> Sequence[Fact]: ...

    def upsert(self, profile_id: str, fact: Fact) -> None: ...

    def delete(self, profile_id: str, fact_id: str) -> None: ...


@dataclass(frozen=True)
class RetrievedChunk:
    id: str
    text: str
    source: str
    score: float


@runtime_checkable
class EmbeddingPort(Protocol):
    def embed(self, text: str) -> Sequence[float]: ...


@runtime_checkable
class RetrievalPort(Protocol):
    def search(self, query: str, limit: int) -> Sequence[RetrievedChunk]: ...


@dataclass(frozen=True)
class ToolDefinition:
    """Contract only: a tool as described to the model (see docs/tasks/tool-loop.md).

    `parameters` is a JSON-schema subset:
    ``{"type": "object", "properties": {...}, "required": [...]}``.
    Not hashable when `parameters` is a dict.
    """

    name: str
    description: str
    parameters: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolCall:
    """One requested call; `arguments` holds decoded JSON values."""

    name: str
    arguments: Mapping[str, object]


@dataclass(frozen=True)
class ToolResult:
    """Text sent back to the model; `error` is set when the call failed."""

    output: str
    error: str | None = None


@runtime_checkable
class ToolPort(Protocol):
    def execute(self, call: ToolCall, cancellation: CancellationToken | None = None) -> ToolResult: ...


@dataclass(frozen=True)
class PermissionRequest:
    action: str
    resource: str


@dataclass(frozen=True)
class PermissionDecision:
    allowed: bool
    reason: str = ""


@runtime_checkable
class PermissionPort(Protocol):
    def check(self, request: PermissionRequest) -> PermissionDecision: ...


FileAction = Literal["read", "write", "create"]


@dataclass(frozen=True)
class FileAccessRule:
    """Typed policy input, not validation; policy constructors validate and copy."""

    path: str
    actions: frozenset[FileAction]
    recursive: bool = False


@runtime_checkable
class FileSystemPort(Protocol):
    """Creator-bound UTF-8 regular-file access, not a security implementation.

    Adapters must enforce per-operation permissions, absolute paths and no
    symlinks (including ancestors). Read/write require an existing file;
    create is exclusive in an existing parent. Denials raise PolicyDenied
    before mutation; other I/O failures raise PortError without file contents.
    See docs/tasks/filesystem-permissions.md for the full contract.
    Runtime protocol checks establish member presence only, not security.
    """

    @property
    def creator_id(self) -> str: ...

    def read_text(self, path: str) -> str: ...

    def write_text(self, path: str, content: str) -> None: ...

    def create_text(self, path: str, content: str) -> None: ...


@dataclass(frozen=True)
class ApprovalRequest:
    action: str
    resource: str
    reason: str


@dataclass(frozen=True)
class ApprovalDecision:
    approved: bool


@runtime_checkable
class ApprovalPort(Protocol):
    def request(self, request: ApprovalRequest) -> ApprovalDecision: ...


@dataclass(frozen=True)
class GuardrailDecision:
    allowed: bool
    text: str | None = None
    reason: str = ""


@runtime_checkable
class GuardrailPort(Protocol):
    def inspect(
        self, text: str, direction: Literal["input", "output"]
    ) -> GuardrailDecision: ...


@dataclass(frozen=True)
class Event:
    name: str
    fields: Mapping[str, str]


@runtime_checkable
class EventPort(Protocol):
    def emit(self, event: Event) -> None: ...
