from dataclasses import FrozenInstanceError

import pytest

from sensai.core.contracts import RetrievalPort
from sensai.core.errors import SensaiError
from sensai.memory.vector_index import IndexChunk, LocalVectorIndex, VectorIndexError


class FakeEmbedding:
    def __init__(self, vectors):
        self.vectors = vectors
        self.calls = []

    def embed(self, text):
        self.calls.append(text)
        return self.vectors[text]


def chunk(id, vector, text=None):
    return IndexChunk(id, text or f"text {id}", vector)


def test_brand_bound_retrieval_is_top_k_cosine_with_stable_ties():
    embed = FakeEmbedding({"question": [1, 0]})
    index = LocalVectorIndex(embed)
    index.upsert("brand-a", "z-source", "v1", chunk("b", [2, 0]))
    index.upsert("brand-a", "a-source", "v1", chunk("z", [1, 0]))
    index.upsert("brand-a", "a-source", "v1", chunk("a", [3, 0]))
    index.upsert("brand-a", "other", "v1", chunk("low", [0, 1]))
    index.upsert("brand-b", "a-source", "v1", chunk("other-brand", [1, 0]))
    search = index.for_brand("brand-a")
    assert isinstance(search, RetrievalPort)
    with pytest.raises(FrozenInstanceError):
        search.brand_id = "brand-b"
    hits = search.search("question", 3)
    assert [(hit.id, hit.source, hit.score) for hit in hits] == [
        ("a", "a-source", 1.0), ("z", "a-source", 1.0), ("b", "z-source", 1.0)
    ]
    assert all("other-brand" != hit.id for hit in search.search("question", 99))
    assert [hit.id for hit in index.for_brand("brand-b").search("question", 2)] == [
        "other-brand"
    ]
    assert index.for_brand("missing").search("question", 2) == ()
    assert embed.calls == ["question", "question", "question"]


def test_cosine_normalizes_query_and_documents_without_mutating_caller_data():
    embed = FakeEmbedding({"q": [10, 0]})
    vector = [3, 4]
    index = LocalVectorIndex(embed)
    index.upsert("a", "src", "v1", chunk("one", vector))
    vector[:] = [0, 0]
    entry, = index.entries("a")
    assert entry.vector == pytest.approx((0.6, 0.8))
    assert (entry.brand_id, entry.source_version) == ("a", "v1")
    assert index.for_brand("a").search("q", 1)[0].score == pytest.approx(0.6)


def test_upsert_same_version_updates_one_id_new_version_drops_old_source():
    index = LocalVectorIndex(FakeEmbedding({"q": [1, 0]}))
    index.upsert("a", "src", "v1", chunk("first", [1, 0]))
    index.upsert("a", "src", "v1", chunk("second", [0, 1]))
    index.upsert("a", "src", "v1", chunk("first", [-1, 0], "replacement"))
    assert [hit.id for hit in index.for_brand("a").search("q", 5)] == [
        "second", "first"
    ]
    index.upsert("a", "src", "v2", chunk("new", [1, 0]))
    assert [(hit.id, hit.text) for hit in index.for_brand("a").search("q", 5)] == [
        ("new", "text new")
    ]
    assert index.entries("a")[0].source_version == "v2"


def test_replace_source_is_complete_atomic_and_brand_local():
    index = LocalVectorIndex(FakeEmbedding({"q": [1, 0]}))
    index.replace_source("a", "src", "v1", [chunk("one", [1, 0]), chunk("two", [0, 1])])
    index.upsert("a", "other", "v1", chunk("stay", [1, 0]))
    index.upsert("b", "src", "v1", chunk("b-only", [1, 0]))
    before = index.entries("a")
    with pytest.raises(VectorIndexError):
        index.replace_source("a", "src", "v2", [chunk("ok", [1, 0]), chunk("bad", [0])])
    assert index.entries("a") == before
    with pytest.raises(VectorIndexError, match="duplicate"):
        index.replace_source("a", "src", "v2", [chunk("dupe", [1, 0]), chunk("dupe", [0, 1])])
    assert index.entries("a") == before
    index.replace_source("a", "src", "v2", [chunk("new", [0, 1])])
    assert {item.id for item in index.entries("a")} == {"new", "stay"}
    assert {item.id for item in index.entries("b")} == {"b-only"}
    index.replace_source("a", "src", "v3", [])
    assert {item.id for item in index.entries("a")} == {"stay"}


def test_version_guarded_invalidation_does_not_remove_newer_source():
    index = LocalVectorIndex(FakeEmbedding({"q": [1]}))
    index.upsert("a", "src", "v2", chunk("a", [1]))
    index.upsert("b", "src", "v1", chunk("b", [1]))
    assert not index.invalidate_source("a", "src", "v1")
    assert not index.invalidate_source("a", "missing")
    assert index.invalidate_source("a", "src", "v2")
    assert index.entries("a") == ()
    assert [item.id for item in index.entries("b")] == ["b"]


@pytest.mark.parametrize("limit", [0, -1, True, 1.5, "2", None])
def test_invalid_limit_rejected_before_embedding(limit):
    embed = FakeEmbedding({"q": [1]})
    index = LocalVectorIndex(embed)
    index.upsert("a", "src", "v1", chunk("a", [1]))
    with pytest.raises(VectorIndexError):
        index.for_brand("a").search("q", limit)
    assert embed.calls == []


@pytest.mark.parametrize(
    "vector",
    [[], [0, 0], [float("nan"), 1], [float("inf"), 1],
     [True, 1], ["1", 0], [1.5e308, 1.5e308]],
)
def test_bad_vectors_rejected_before_mutation(vector):
    index = LocalVectorIndex(FakeEmbedding({"q": [1, 0]}))
    with pytest.raises(VectorIndexError) as caught:
        index.upsert("a", "src", "v1", chunk("bad", vector))
    assert isinstance(caught.value, SensaiError)
    assert index.entries("a") == ()


def test_dimension_mismatch_on_insert_and_query():
    embed = FakeEmbedding({"wrong": [1, 0, 0], "zero": [0, 0], "nan": [float("nan"), 0]})
    index = LocalVectorIndex(embed)
    index.upsert("a", "src", "v1", chunk("ok", [1, 0]))
    with pytest.raises(VectorIndexError, match="dimensions"):
        index.upsert("b", "src", "v1", chunk("bad", [1, 0, 0]))
    for query in ("wrong", "zero", "nan"):
        with pytest.raises(VectorIndexError):
            index.for_brand("a").search(query, 1)
    assert index.entries("b") == ()


@pytest.mark.parametrize("brand,source,version,id,text", [
    ("", "src", "v1", "one", "text"),
    ("a", "", "v1", "one", "text"),
    ("a", "src", "", "one", "text"),
    ("a", "src", "v1", "", "text"),
    ("a", "src", "v1", "one", ""),
])
def test_required_identifiers_and_text(brand, source, version, id, text):
    index = LocalVectorIndex(FakeEmbedding({}))
    with pytest.raises(VectorIndexError):
        index.upsert(brand, source, version, IndexChunk(id, text, [1]))


def test_empty_index_does_not_embed_but_invalid_query_is_rejected():
    embed = FakeEmbedding({})
    index = LocalVectorIndex(embed)
    assert index.for_brand("a").search("q", 1) == ()
    with pytest.raises(VectorIndexError):
        index.for_brand("a").search(" ", 1)
    assert embed.calls == []


def test_nonfinite_similarity_is_rejected(monkeypatch):
    index = LocalVectorIndex(FakeEmbedding({"q": [1]}))
    index.upsert("a", "src", "v1", chunk("id", [1]))
    monkeypatch.setattr("sensai.memory.vector_index.math.fsum", lambda _: float("nan"))
    with pytest.raises(VectorIndexError, match="non-finite"):
        index.for_brand("a").search("q", 1)
