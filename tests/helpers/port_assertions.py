"""Reusable port assertions shared by the fake and real adapter tests."""

from sensai.core.ports import (
    Fact,
    FactStorePort,
    LLMStreamPort,
    Profile,
    ProfileStorePort,
    SessionSnapshot,
    SessionStorePort,
)
from sensai.core.messages import Message


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
