"""Deterministic local substitutes for B1 and feature ports."""

from collections.abc import Iterator, Mapping, Sequence

from sensai.core.contracts import (
    CancellationToken,
    Event,
    Fact,
    Persona,
    PortError,
    Profile,
    RetrievedChunk,
    SessionSnapshot,
    ToolCall,
    ToolResult,
)
from sensai.llm.base import LLMClient
from sensai.core.messages import Message


class FakeClient(LLMClient):
    """Replays scripted chunks/errors (including mid-stream) and records calls."""

    def __init__(self, *replies: Sequence[str | Exception] | Exception):
        self.replies = list(replies)
        self.calls: list[list[str]] = []
        self.requests: list[tuple[str, tuple[Message, ...]]] = []

    def stream(self, model: str, messages: Sequence[Message], cancellation: CancellationToken | None = None) -> Iterator[str]:
        if cancellation is not None:
            cancellation.raise_if_cancelled()
        self.calls.append([m.content for m in messages])
        self.requests.append((model, tuple(messages)))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        for chunk in reply:
            if cancellation is not None:
                cancellation.raise_if_cancelled()
            if isinstance(chunk, Exception):
                raise chunk
            yield chunk


class FakeOllama(FakeClient):
    """Scripted Ollama-shaped stream, without HTTP or a local model."""


class FakePersonaStore:
    def __init__(self, personas: Sequence[Persona] = ()):
        self.personas = {persona.id: persona for persona in personas}

    def get(self, persona_id: str) -> Persona | None:
        return self.personas.get(persona_id)


class FakeSessionStore:
    def __init__(self):
        self.sessions: dict[str, SessionSnapshot] = {}

    def load(self, session_id: str) -> SessionSnapshot | None:
        return self.sessions.get(session_id)

    def save(self, session: SessionSnapshot) -> None:
        self.sessions[session.id] = session

    def delete(self, session_id: str) -> None:
        self.sessions.pop(session_id, None)


class FakeProfileStore:
    def __init__(self):
        self.profiles: dict[str, Profile] = {}

    def load(self, profile_id: str) -> Profile | None:
        profile = self.profiles.get(profile_id)
        return Profile(profile.id, dict(profile.preferences)) if profile else None

    def save(self, profile: Profile) -> None:
        self.profiles[profile.id] = Profile(profile.id, dict(profile.preferences))

    def delete(self, profile_id: str) -> None:
        self.profiles.pop(profile_id, None)


class FakeFactStore:
    def __init__(self):
        self.facts: dict[str, dict[str, Fact]] = {}

    def list_for(self, profile_id: str) -> Sequence[Fact]:
        return tuple(self.facts.get(profile_id, {}).values())

    def upsert(self, profile_id: str, fact: Fact) -> None:
        self.facts.setdefault(profile_id, {})[fact.id] = fact

    def delete(self, profile_id: str, fact_id: str) -> None:
        self.facts.get(profile_id, {}).pop(fact_id, None)


class FakeStorage:
    def __init__(self, personas: Sequence[Persona] = ()):
        self.personas = FakePersonaStore(personas)
        self.sessions = FakeSessionStore()
        self.profiles = FakeProfileStore()
        self.facts = FakeFactStore()


class FakeEmbedding:
    def embed(self, text: str) -> Sequence[float]:
        return (float(len(text)), float(sum(map(ord, text))))


class FakeRetrieval:
    def __init__(self, chunks: Sequence[RetrievedChunk] = ()):
        self.chunks = tuple(chunks)
        self.queries: list[tuple[str, int]] = []

    def search(self, query: str, limit: int) -> Sequence[RetrievedChunk]:
        self.queries.append((query, limit))
        return sorted(self.chunks, key=lambda chunk: -chunk.score)[:limit]


class FakeTool:
    def __init__(self, results: Mapping[str, ToolResult]):
        self.results = dict(results)
        self.calls: list[ToolCall] = []

    def execute(self, call: ToolCall, cancellation: CancellationToken | None = None) -> ToolResult:
        if cancellation is not None:
            cancellation.raise_if_cancelled()
        self.calls.append(call)
        try:
            return self.results[call.name]
        except KeyError as exc:
            raise PortError(f"unknown tool: {call.name}") from exc


class FakeEventSink:
    def __init__(self):
        self.events: list[Event] = []

    def emit(self, event: Event) -> None:
        self.events.append(event)
