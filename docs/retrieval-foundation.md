# Retrieval foundation (T16 / #29 and T17 / #30)

This is an **enabler**, not document ingestion, cited answers, or an R1
feature. The caller owns source authorization, chunking, embedding documents,
version ordering, and context/citation assembly. No production data or live
Ollama service is required by the unit tests.

## Embeddings

`OllamaEmbeddingAdapter(model, host="http://localhost:11434",
timeout=60.0, dimensions=None)` implements `EmbeddingPort.embed(text)`. It
directly POSTs `{"model": model, "input": text}` to `/api/embed` and expects
exactly one nonempty `embeddings` vector. Vectors must contain finite numbers
with a finite nonzero norm. The first successful response pins the adapter's
dimension; pass `dimensions` to pin it before the first call (for example,
when loading an existing index). Every received HTTP response is closed even
on failure. An invalid response or failed close cannot change that pin.
If close fails while handling an earlier response error, the earlier error
remains primary; neither error exposes the raw close exception.

`EmbeddingError`, `EmbeddingResponseError`, and `EmbeddingDimensionError` are
`LLMError` / `SensaiError` subclasses. Connection failures raise the existing
`LLMConnectionError`; HTTP 404 raises `ModelNotFoundError`; other HTTP failures
and timeouts raise `EmbeddingError`. Error messages never contain input text,
raw server errors, or exception strings. The caller should not log raw input
or the underlying HTTP request.

## Local vector index

`LocalVectorIndex(embedding)` holds **only in-memory** vectors. It has no
disk/database persistence: process exit loses every entry. A caller must
rebuild it from authorized, versioned sources on restart. It does not fetch,
embed or validate documents; `IndexChunk` takes an id, display text and
precomputed vector. Example with fictional data:

```python
from sensai.llm.embeddings import OllamaEmbeddingAdapter
from sensai.vector_index import IndexChunk, LocalVectorIndex

embedding = OllamaEmbeddingAdapter("nomic-embed-text")
index = LocalVectorIndex(embedding)
index.replace_source(
    "fictional-brand", "fictional-guide", "2026-09-30",
    [IndexChunk("guide-1", "Fictional approved product description",
                embedding.embed("Fictional approved product description"))],
)
retrieval = index.for_brand("fictional-brand")  # RetrievalPort
hits = retrieval.search("product description", limit=5)
```

Bind brand context **before** searching: `for_brand(brand_id)` returns a
`RetrievalPort` whose `search(query, limit)` cannot select another brand.
`entries(brand_id)` exposes frozen `IndexedChunk` snapshots with `brand_id`,
`source`, `source_version`, `id`, `text` and a copied, normalized vector.
`RetrievedChunk.source` is the source id; the port does not carry source
version or citations, so consumers needing versions must use index metadata
and must not present these hits as cited evidence.

`upsert(brand_id, source, source_version, chunk)` updates one chunk at the
same version; changing a source's version drops its old chunks first.
`replace_source(brand_id, source, source_version, chunks)` atomically swaps
the full source (including removal via an empty sequence). Failed validation
leaves old contents intact. `invalidate_source(brand_id, source,
source_version=None)` removes a source, returning whether it was removed;
when a version is provided, an older invalidation cannot remove a different
current version. Versions are **opaque identifiers**, not sortable timestamps:
callers must serialize updates and reject stale writes themselves. Operations
are single-threaded; external synchronization is required for concurrent
writes/searches.

All stored and query vectors must have the same dimension and a finite
nonzero norm. The first stored vector pins the index dimension for its
lifetime, even after entries are invalidated; create a new index to switch
embedding models/dimensions. Cosine scores are computed over normalized
copies. Search requires a positive integer `limit` (excluding booleans); an
empty brand returns no hits without embedding the query. Results sort by
descending score, then ascending source id and chunk id for deterministic ties.
`VectorIndexError` (a `PortError` / `SensaiError`) reports invalid metadata,
vectors, dimensions, scores or limits. Neither this index nor the embedding
adapter provides tenant authorization, privacy filtering or claim approval.
