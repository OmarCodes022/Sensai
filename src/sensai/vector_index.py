"""In-memory, brand-scoped cosine retrieval over caller-supplied vectors."""

import math
from collections.abc import Sequence
from dataclasses import dataclass

from sensai.contracts import EmbeddingPort, PortError, RetrievedChunk


class VectorIndexError(PortError):
    """Invalid index data or retrieval request."""


@dataclass(frozen=True)
class IndexChunk:
    id: str
    text: str
    vector: Sequence[float]


@dataclass(frozen=True)
class IndexedChunk:
    brand_id: str
    source: str
    source_version: str
    id: str
    text: str
    vector: tuple[float, ...]


def _required(value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise VectorIndexError("index metadata and text must not be empty")


def _normalize(vector: Sequence[float], dimension: int | None) -> tuple[float, ...]:
    if (
        isinstance(vector, (str, bytes))
        or not isinstance(vector, Sequence)
        or not vector
    ):
        raise VectorIndexError("vector must be a nonempty numeric sequence")
    if dimension is not None and len(vector) != dimension:
        raise VectorIndexError("vector dimensions do not match")
    if any(
        isinstance(value, bool) or not isinstance(value, (int, float))
        for value in vector
    ):
        raise VectorIndexError("vector must contain finite numbers")
    try:
        values = tuple(float(value) for value in vector)
    except OverflowError:
        raise VectorIndexError("vector must contain finite numbers") from None
    if not all(math.isfinite(value) for value in values):
        raise VectorIndexError("vector must contain finite numbers")
    norm = math.hypot(*values)
    if not math.isfinite(norm) or norm == 0:
        raise VectorIndexError("vector must have a finite nonzero norm")
    return tuple(value / norm for value in values)


@dataclass(frozen=True)
class BrandRetrieval:
    """A brand-bound RetrievalPort; no brand selection is accepted at search time."""

    _index: "LocalVectorIndex"
    brand_id: str

    def __post_init__(self) -> None:
        _required(self.brand_id)

    def search(self, query: str, limit: int) -> tuple[RetrievedChunk, ...]:
        return self._index._search(self.brand_id, query, limit)


class LocalVectorIndex:
    """Volatile index; source replacements are atomic in this single-threaded adapter."""

    def __init__(self, embedding: EmbeddingPort):
        self.embedding = embedding
        self._sources: dict[str, dict[str, dict[str, IndexedChunk]]] = {}
        self._dimension: int | None = None

    def for_brand(self, brand_id: str) -> BrandRetrieval:
        return BrandRetrieval(self, brand_id)

    def _prepare(
        self, brand_id: str, source: str, source_version: str, chunk: IndexChunk
    ) -> IndexedChunk:
        if not isinstance(chunk, IndexChunk):
            raise VectorIndexError("expected an IndexChunk")
        for value in (brand_id, source, source_version, chunk.id, chunk.text):
            _required(value)
        normalized = _normalize(chunk.vector, self._dimension)
        return IndexedChunk(
            brand_id, source, source_version, chunk.id, chunk.text, normalized
        )

    def upsert(
        self, brand_id: str, source: str, source_version: str, chunk: IndexChunk
    ) -> None:
        entry = self._prepare(brand_id, source, source_version, chunk)
        sources = self._sources.setdefault(brand_id, {})
        existing = sources.get(source)
        if (
            existing is None
            or next(iter(existing.values())).source_version != source_version
        ):
            sources[source] = {entry.id: entry}
        else:
            existing[entry.id] = entry
        self._dimension = len(entry.vector)

    def replace_source(
        self,
        brand_id: str,
        source: str,
        source_version: str,
        chunks: Sequence[IndexChunk],
    ) -> None:
        for value in (brand_id, source, source_version):
            _required(value)
        if isinstance(chunks, (str, bytes)) or not isinstance(chunks, Sequence):
            raise VectorIndexError("chunks must be a sequence")
        entries: dict[str, IndexedChunk] = {}
        for chunk in chunks:
            entry = self._prepare(brand_id, source, source_version, chunk)
            if entries and len(entry.vector) != len(next(iter(entries.values())).vector):
                raise VectorIndexError("vector dimensions do not match")
            if entry.id in entries:
                raise VectorIndexError("duplicate chunk id in source")
            entries[entry.id] = entry
        if entries:
            self._sources.setdefault(brand_id, {})[source] = entries
            self._dimension = len(next(iter(entries.values())).vector)
        else:
            self.invalidate_source(brand_id, source)

    def invalidate_source(
        self, brand_id: str, source: str, source_version: str | None = None
    ) -> bool:
        _required(brand_id)
        _required(source)
        if source_version is not None:
            _required(source_version)
        sources = self._sources.get(brand_id)
        if not sources or source not in sources:
            return False
        if source_version is not None and (
            next(iter(sources[source].values())).source_version != source_version
        ):
            return False
        del sources[source]
        if not sources:
            del self._sources[brand_id]
        return True

    def entries(self, brand_id: str) -> tuple[IndexedChunk, ...]:
        _required(brand_id)
        return tuple(
            entry
            for source in sorted(self._sources.get(brand_id, {}))
            for entry in sorted(
                self._sources[brand_id][source].values(), key=lambda item: item.id
            )
        )

    def _search(
        self, brand_id: str, query: str, limit: int
    ) -> tuple[RetrievedChunk, ...]:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise VectorIndexError("limit must be a positive integer")
        _required(query)
        entries = self.entries(brand_id)
        if not entries:
            return ()
        vector = _normalize(self.embedding.embed(query), self._dimension)
        ranked = []
        for entry in entries:
            score = math.fsum(a * b for a, b in zip(vector, entry.vector))
            if not math.isfinite(score):
                raise VectorIndexError("non-finite similarity score")
            ranked.append((score, entry))
        ranked.sort(key=lambda pair: (-pair[0], pair[1].source, pair[1].id))
        return tuple(
            RetrievedChunk(entry.id, entry.text, entry.source, score)
            for score, entry in ranked[:limit]
        )
