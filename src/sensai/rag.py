"""Brand document search: load Markdown documents, index their chunks, answer search_docs."""
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from sensai.core.errors import LLMError, ModelNotFoundError
from sensai.core.ports import ToolDefinition, ToolResult
from sensai.llm.embeddings import OllamaEmbeddingAdapter
from sensai.memory.vector_index import IndexChunk, LocalVectorIndex, VectorIndexError

SEARCH_DOCS = ToolDefinition(
    name="search_docs",
    description="Search the brand documents for relevant information",
    parameters={
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    },
)

# Added to the system prompt only when document search is on: without the tool, the model
# would be told to call something that does not exist.
DOCS_PROMPT = """Document search:
- For any question about the brand's products, claims, ingredients, policies, or FAQ, call search_docs first.
- Answer only from what search_docs returns. Cite the source names in your answer.
- A result marked OUTDATED is an old version: do not present it as current, use the newer one.
- If the results do not contain the answer, say clearly that the documents do not cover it. Do not invent or guess."""

# A document starts with a header between two lines of three dashes; the file's first line is the first.
_FRONT_MATTER = re.compile(r"---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)(.*)", re.DOTALL)


@dataclass
class DocSearch:
    """Everything the chat needs to search, list and reindex the documents of one folder."""
    index: LocalVectorIndex
    docs: list[dict]
    folder: str
    creator_id: str
    embed_model: str


def load_documents(folder: str, skipped: list[str] | None = None) -> list[dict]:
    """The folder's Markdown documents, sorted by file name. Files without a header are not
    documents: their names are added to `skipped` (when given) instead of being half-read.
    A README.md is never a document and is left out silently."""
    docs = []
    for path in sorted(Path(folder).glob("*.md")):
        if path.name.lower() == "readme.md":
            continue  # Notes about the folder, not a document.
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            match = None
        else:
            match = _FRONT_MATTER.match(text)
        if match is None:
            if skipped is not None:
                skipped.append(path.name)
            continue
        header = {}
        for line in match.group(1).splitlines():
            if ": " in line:
                key, value = line.split(": ", 1)
                header[key.strip()] = value.strip()
        docs.append({
            "source": header.get("source", path.stem),
            "version": header.get("version", ""),
            "product": header.get("product", ""),
            "title": header.get("title", path.stem),
            "text": match.group(2).strip(),
        })
    return docs


def chunk_text(text: str) -> list[str]:
    chunks = text.split("\n\n")
    return [c.strip() for c in chunks if len(c.strip()) >= 10]


def build_index(docs: list[dict], embedding: OllamaEmbeddingAdapter, index: LocalVectorIndex, creator_id: str) -> int:
    """Index every document and drop sources that are no longer in `docs`; returns the chunk count.

    All embedding happens first, so a failure leaves the previous index untouched."""
    prepared = []
    for doc in docs:
        chunks = chunk_text(doc["text"])
        prepared.append((doc, [IndexChunk(f"{doc['source']}-{i}", chunk, embedding.embed(chunk))
                               for i, chunk in enumerate(chunks)]))
    for source in {entry.source for entry in index.entries(creator_id)} - {doc["source"] for doc in docs}:
        index.invalidate_source(creator_id, source)
    for doc, index_chunks in prepared:
        index.replace_source(creator_id, doc["source"], doc["version"], index_chunks)
    return sum(len(index_chunks) for _, index_chunks in prepared)


def superseded_by(doc: dict, docs: list[dict]) -> dict | None:
    """The newest document of the same product with a later version, if any."""
    if not doc.get("product"):
        return None
    newer = [d for d in docs if d.get("product") == doc["product"] and d["version"] > doc["version"]]
    return max(newer, key=lambda d: d["version"], default=None)


def search_docs_handler(arguments: dict, cancellation, *, index: LocalVectorIndex, creator_id: str, docs_meta: list[dict]) -> ToolResult:
    query = arguments.get("query", "")
    results = index.for_brand(creator_id).search(query, 3)
    if not results:
        return ToolResult(output="No relevant documents found")
    lines = []
    for hit in results:
        doc = next((d for d in docs_meta if d["source"] == hit.source), None)
        label = f"{hit.source}, {doc['version'] if doc else ''}"
        newer = superseded_by(doc, docs_meta) if doc else None
        if newer:
            label += f", OUTDATED: superseded by {newer['source']} {newer['version']}"
        lines.append(f"[{label}] {hit.text}")
    return ToolResult(output="\n".join(lines))


def _failure(error: Exception, model: str) -> list[str]:
    hint = f" (try: ollama pull {model})" if isinstance(error, ModelNotFoundError) else ""
    return [f"error: {error}{hint}"]


def docs_command(search: DocSearch, argument: str = "") -> list[str]:
    """`/docs`: the indexed documents; `/docs <text>`: what a search for that text finds."""
    if not argument.strip():
        counts = Counter(entry.source for entry in search.index.entries(search.creator_id))
        versions = {entry.source: entry.source_version for entry in search.index.entries(search.creator_id)}
        return [f"{source}   {versions[source]}   {counts[source]} chunks" for source in sorted(counts)]
    try:
        results = search.index.for_brand(search.creator_id).search(argument, 3)
    except (LLMError, VectorIndexError) as error:
        return _failure(error, search.embed_model)
    return [f"[{i}] {hit.source} · score {hit.score:.2f}\n    {hit.text[:120]}"
            for i, hit in enumerate(results, 1)] or ["No relevant documents found"]


def reindex_command(search: DocSearch) -> list[str]:
    """`/reindex`: read the folder again; a failure leaves the previous index and list in place."""
    skipped: list[str] = []
    docs = load_documents(search.folder, skipped)
    lines = [f"warning: skipped {name}: no header between --- lines" for name in skipped]
    try:
        total = build_index(docs, search.index.embedding, search.index, search.creator_id)
    except (LLMError, VectorIndexError) as error:
        return lines + _failure(error, search.embed_model)
    search.docs[:] = docs
    return lines + [f"Reindexed {len(docs)} documents ({total} chunks)."]
