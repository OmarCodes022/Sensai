"""Reusable port assertions run by ordinary pytest, without Ollama or disk."""

import json

import pytest

from fakes import (
    FakeEmbedding,
    FakeEventSink,
    FakeOllama,
    FakeRetrieval,
    FakeStorage,
    FakeTool,
)
from sensai.contracts import (
    ApprovalDecision,
    ApprovalPort,
    ApprovalRequest,
    B1SessionAdapter,
    CancellationToken,
    ConversationPort,
    EmbeddingPort,
    Event,
    EventPort,
    Fact,
    FactStorePort,
    GuardrailDecision,
    GuardrailPort,
    LLMStreamPort,
    OperationCancelled,
    PermissionDecision,
    PermissionPort,
    PermissionRequest,
    Persona,
    PersonaPort,
    PolicyDenied,
    PortError,
    Profile,
    ProfileStorePort,
    RetrievedChunk,
    RetrievalPort,
    SessionSnapshot,
    SessionStorePort,
    ToolCall,
    ToolPort,
    ToolResult,
)
from sensai.errors import LLMError, SensaiError
from sensai.llm.ollama import OllamaClient
from sensai.messages import Message
from sensai.session import ChatSession


def assert_stream_contract(client: LLMStreamPort) -> None:
    messages = [Message(role="system", content="sys"), Message(role="user", content="hi")]
    stream = client.stream("model", messages)
    assert next(stream) == "Hel"
    assert list(stream) == ["lo"]


def assert_session_store_contract(store: SessionStorePort) -> None:
    snapshot = SessionSnapshot("session", (Message(role="system", content="sys"),))
    assert store.load(snapshot.id) is None
    store.save(snapshot)
    assert store.load(snapshot.id) == snapshot
    store.delete(snapshot.id)
    assert store.load(snapshot.id) is None


def assert_profile_store_contract(store: ProfileStorePort) -> None:
    profile = Profile("user", {"tone": "brief"})
    assert store.load(profile.id) is None
    store.save(profile)
    assert store.load(profile.id) == profile
    store.delete(profile.id)
    assert store.load(profile.id) is None


def assert_fact_store_contract(store: FactStorePort) -> None:
    fact = Fact("fact", "prefers Python", "user")
    assert not store.list_for("user")
    store.upsert("user", fact)
    assert store.list_for("user") == (fact,)
    store.delete("user", fact.id)
    assert not store.list_for("user")


def test_b1_reference_implements_stream_and_conversation_ports():
    assert isinstance(OllamaClient(), LLMStreamPort)
    session = ChatSession(FakeOllama(), "model", "sys")
    assert isinstance(session, ConversationPort)


def test_fake_ollama_stream_contract_and_b1_history():
    client = FakeOllama(["Hel", "lo"], ["again"])
    assert_stream_contract(client)
    session = ChatSession(client, "model", "sys")
    adapter = B1SessionAdapter(session)
    assert isinstance(adapter, ConversationPort)
    assert list(adapter.send("second")) == ["again"]
    assert client.requests[1] == (
        "model",
        (Message(role="system", content="sys"), Message(role="user", content="second")),
    )
    assert adapter.history == (
        Message(role="system", content="sys"),
        Message(role="user", content="second"),
        Message(role="assistant", content="again"),
    )


def test_real_b1_client_with_scripted_http_preserves_stream_and_history(monkeypatch):
    calls = []

    class Response:
        status_code = 200

        def iter_lines(self):
            yield json.dumps({"message": {"role": "assistant", "content": "Hel"}}).encode()
            yield json.dumps({"message": {"role": "assistant", "content": "lo"}}).encode()
            yield b'{"done": true}'

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    monkeypatch.setattr("sensai.llm.ollama.requests.post", post)
    client = OllamaClient()
    assert_stream_contract(client)
    session = ChatSession(client, "model", "sys")
    assert list(B1SessionAdapter(session).send("hi")) == ["Hel", "lo"]
    assert calls[-1][1]["json"]["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hi"},
    ]
    assert calls[-1][1]["json"]["stream"] is True
    assert session.messages[-1] == Message(role="assistant", content="Hello")


def test_adapter_history_across_turns_and_failed_turn():
    client = FakeOllama(["A1"], LLMError("offline"), ["A2"])
    adapter = B1SessionAdapter(ChatSession(client, "model", "sys"))
    assert list(adapter.send("Q1")) == ["A1"]
    with pytest.raises(LLMError, match="offline"):
        list(adapter.send("retry"))
    assert [message.content for message in adapter.history] == ["sys", "Q1", "A1"]
    assert list(adapter.send("Q2")) == ["A2"]
    assert [message.content for message in client.requests[-1][1]] == [
        "sys", "Q1", "A1", "Q2",
    ]
    with pytest.raises(ValueError, match="empty input"):
        list(adapter.send(" "))
    assert len(adapter.history) == 5


def test_midstream_failure_is_not_committed():
    for failure in (LLMError("disconnected"), PortError("storage offline")):
        adapter = B1SessionAdapter(
            ChatSession(FakeOllama(["partial", failure]), "model", "sys")
        )
        stream = adapter.send("hi")
        assert next(stream) == "partial"
        with pytest.raises(type(failure), match=str(failure)):
            next(stream)
        assert [message.content for message in adapter.history] == ["sys"]


def test_adapter_cancellation_and_early_close_roll_back_pending_turn():
    for interrupt in ("token", "close"):
        client = FakeOllama(["one", "two"])
        adapter = B1SessionAdapter(ChatSession(client, "model", "sys"))
        token = CancellationToken()
        stream = adapter.send("question", token)
        assert next(stream) == "one"
        if interrupt == "token":
            token.cancel()
            with pytest.raises(OperationCancelled):
                next(stream)
        else:
            stream.close()
        assert [message.content for message in adapter.history] == ["sys"]
    token = CancellationToken()
    token.cancel()
    with pytest.raises(OperationCancelled):
        list(adapter.send("never sent", token))
    assert len(client.requests) == 1


def test_storage_ports_are_isolated_and_delete():
    storage = FakeStorage([Persona("tutor", "Teach briefly.")])
    assert isinstance(storage.personas, PersonaPort)
    assert isinstance(storage.sessions, SessionStorePort)
    assert isinstance(storage.profiles, ProfileStorePort)
    assert isinstance(storage.facts, FactStorePort)
    assert storage.personas.get("tutor") == Persona("tutor", "Teach briefly.")
    assert storage.personas.get("missing") is None
    assert_session_store_contract(storage.sessions)
    assert_profile_store_contract(storage.profiles)
    assert_fact_store_contract(storage.facts)
    storage.sessions.save(SessionSnapshot("same", ()))
    storage.profiles.save(Profile("same", {"key": "value"}))
    assert storage.sessions.load("same") is not None
    assert storage.profiles.load("same") is not None
    storage.sessions.delete("same")
    assert storage.profiles.load("same") is not None
    preferences = {"tone": "brief"}
    storage.profiles.save(Profile("copy", preferences))
    preferences["tone"] = "verbose"
    loaded = storage.profiles.load("copy")
    assert loaded is not None
    assert loaded.preferences["tone"] == "brief"


def test_embedding_retrieval_tool_and_event_fakes():
    embedding: EmbeddingPort = FakeEmbedding()
    assert embedding.embed("abc") == embedding.embed("abc")
    assert embedding.embed("abc") != embedding.embed("abd")
    chunks = (
        RetrievedChunk("low", "A", "local", 0.2),
        RetrievedChunk("high", "B", "local", 0.9),
    )
    retrieval: RetrievalPort = FakeRetrieval(chunks)
    assert [chunk.id for chunk in retrieval.search("question", 1)] == ["high"]
    assert retrieval.queries == [("question", 1)]
    tool: ToolPort = FakeTool({"read": ToolResult("ok")})
    assert tool.execute(ToolCall("read", {"path": "allowed"})) == ToolResult("ok")
    with pytest.raises(PortError, match="unknown tool"):
        tool.execute(ToolCall("missing", {}))
    events: EventPort = FakeEventSink()
    events.emit(Event("tool.finished", {"tool": "read"}))
    assert events.events == [Event("tool.finished", {"tool": "read"})]


def test_policy_ports_share_decision_types_without_policy_implementation():
    class DenyPolicy:
        def check(self, request: PermissionRequest) -> PermissionDecision:
            return PermissionDecision(False, f"not allowed: {request.resource}")

        def request(self, request: ApprovalRequest) -> ApprovalDecision:
            return ApprovalDecision(False)

        def inspect(self, text: str, direction: str) -> GuardrailDecision:
            return GuardrailDecision(False, reason=f"blocked {direction}")

    policy = DenyPolicy()
    permission: PermissionPort = policy
    approval: ApprovalPort = policy
    guardrail: GuardrailPort = policy
    assert not permission.check(PermissionRequest("read", "private")).allowed
    assert not approval.request(ApprovalRequest("read", "private", "needed")).approved
    assert not guardrail.inspect("secret", "input").allowed
    assert issubclass(PolicyDenied, SensaiError)


def test_sample_persistence_adapter_uses_ports_and_commits_only_complete_turns():
    class PersistedChat:
        def __init__(
            self, session_id: str, persona_id: str, conversation: B1SessionAdapter,
            store: SessionStorePort, events: EventPort,
        ):
            self.session_id = session_id
            self.persona_id = persona_id
            self.conversation = conversation
            self.store = store
            self.events = events

        def send(self, text: str, cancellation: CancellationToken | None = None):
            yield from self.conversation.send(text, cancellation)
            self.store.save(
                SessionSnapshot(self.session_id, self.conversation.history, self.persona_id)
            )
            self.events.emit(Event("turn.completed", {"session_id": self.session_id}))

    storage = FakeStorage([Persona("tutor", "Teach briefly.")])
    prompt = storage.personas.get("tutor")
    assert prompt is not None
    client = FakeOllama(["Hel", "lo"], ["interrupted"])
    app = PersistedChat(
        "session-1",
        prompt.id,
        B1SessionAdapter(ChatSession(client, "model", prompt.system_prompt)),
        storage.sessions,
        FakeEventSink(),
    )
    assert list(app.send("hi")) == ["Hel", "lo"]
    saved = storage.sessions.load("session-1")
    assert saved is not None
    assert saved.persona_id == "tutor"
    assert [message.content for message in saved.messages] == [
        "Teach briefly.", "hi", "Hello",
    ]
    assert app.events.events == [Event("turn.completed", {"session_id": "session-1"})]
    cancelled = CancellationToken()
    stream = app.send("later", cancelled)
    assert next(stream) == "interrupted"
    cancelled.cancel()
    with pytest.raises(OperationCancelled):
        next(stream)
    assert storage.sessions.load("session-1") == saved
    assert len(app.events.events) == 1
