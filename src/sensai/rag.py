from pathlib import Path
from sensai.llm.embeddings import OllamaEmbeddingAdapter
from sensai.memory.vector_index import IndexChunk, LocalVectorIndex
from sensai.core.ports import ToolDefinition, ToolResult

SEARCH_DOCS = ToolDefinition(
    name="search_docs",
    description="Search the brand documents for relevant information",
    parameters={
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    },
)

def load_documents(folder: str) -> list[dict]:
    docs = []
    for path in Path(folder).glob("*.md"):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        parts = text.split("---", 2)
        if len(parts) < 3:
            continue
        header_raw = parts[1]
        header = {}
        for line in header_raw.strip().splitlines():
            if ": " in line:
                key, value = line.split(": ", 1)
                header[key.strip()] = value.strip()
        content = parts[2]
        docs.append({
            "source": header.get("source", path.stem),
            "version": header.get("version", ""),
            "title": header.get("title", path.stem),
            "text": content.strip(),
        })
    return docs

def chunk_text(text: str) -> list[str]:
    chunks = text.split("\n\n")
    return [c.strip() for c in chunks if len(c.strip()) >= 10]

def build_index(docs: list[dict], embedding: OllamaEmbeddingAdapter, index: LocalVectorIndex, creator_id: str) -> int:
    total = 0
    for doc in docs:
        chunks = chunk_text(doc["text"])
        index_chunks = []
        for i, chunk in enumerate(chunks):
            vector = embedding.embed(chunk)
            index_chunks.append(IndexChunk(f"{doc['source']}-{i}", chunk, vector))
        index.replace_source(creator_id, doc["source"], doc["version"], index_chunks)
        total += len(index_chunks)
    return total

def search_docs_handler(arguments: dict, cancellation, *, index: LocalVectorIndex, creator_id: str, docs_meta: list[dict]) -> ToolResult:
    query = arguments.get("query", "")
    results = index.for_brand(creator_id).search(query, 3)
    if not results:
        return ToolResult(output="No relevant documents found")
    lines = []
    for hit in results:
        version = next((d["version"] for d in docs_meta if d["source"] == hit.source), "")
        lines.append(f"[{hit.source}, {version}] {hit.text}")
    return ToolResult(output="\n".join(lines))