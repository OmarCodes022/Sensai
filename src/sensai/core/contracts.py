"""Small, backend-independent boundaries for features built around B1 chat."""

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from sensai.core.errors import SensaiError
from sensai.core.cancellation import CancellationToken, OperationCancelled, OperationTimedOut
from sensai.core.messages import Message
from sensai.app.session import ChatSession


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


class B1SessionAdapter:
    """Expose B1 history and roll back an interrupted in-memory turn.

    Consumption is single-threaded, as with ChatSession. The backend owns
    interrupting blocked requests; the session owns complete-turn history.
    """

    def __init__(self, session: ChatSession):
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
class ToolCall:
    name: str
    arguments: Mapping[str, str]


@dataclass(frozen=True)
class ToolResult:
    output: str


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
