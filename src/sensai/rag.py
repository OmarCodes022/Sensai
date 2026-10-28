"""Brand document search: a folder of documents that stays indexed by itself.

`DocLibrary` watches one folder (data/docs by default). New, edited and removed
files are noticed by a cheap scan and indexed in the background; the model
searches them through the `search_docs` tool, and `add`/`remove` are what the
`/add` and `/remove` commands and the web page call.
"""
import hashlib
import json
import os
import re
import shlex
import sqlite3
import tempfile
import threading
from datetime import datetime, timezone
from time import monotonic

from sensai.core.errors import LLMError, ModelNotFoundError
from sensai.core.ports import ToolDefinition, ToolResult
from sensai.memory.vector_index import IndexChunk, LocalVectorIndex, VectorIndexError

DEFAULT_FOLDER = "data/docs"
TYPES = (".md", ".txt")
MAX_FILE_BYTES = 2 * 2**20
MAX_TOTAL_BYTES = 20 * 2**20
RETRY_SECONDS = 30.0
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}\Z")

SEARCH_DOCS = ToolDefinition(
    name="search_docs",
    description="Search the brand documents (product sheets, FAQ, brand voice) for relevant information",
    parameters={
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    },
)

# Added to the system prompt only while there are documents to search.
DOCS_PROMPT = """Document search:
- For any question about the brand's products, claims, ingredients, policies, or FAQ, call search_docs first.
- Answer only from what search_docs returns. Cite the source names in your answer.
- A result marked OUTDATED is an old version: do not present it as current, use the newer one.
- If the results do not contain the answer, say clearly that the documents do not cover it. Do not invent or guess."""

# An optional header between two lines of three dashes, starting on the file's first line.
_FRONT_MATTER = re.compile(r"---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)(.*)", re.DOTALL)


class DocError(ValueError):
    """A document could not be added or removed; the message is meant for the person."""


def chunk_text(text: str) -> list[str]:
    return [c.strip() for c in text.split("\n\n") if len(c.strip()) >= 10]


def parse_document(name: str, text: str, modified: float) -> dict:
    """Header fields when the file has a header, else defaults (file name, modified date)."""
    stem = name.rsplit(".", 1)[0]
    header, body = {}, text
    match = _FRONT_MATTER.match(text)
    if match is not None:
        body = match.group(2)
        for line in match.group(1).splitlines():
            if ": " in line:
                key, value = line.split(": ", 1)
                header[key.strip()] = value.strip()
    return {"file": name, "source": header.get("source", stem),
            "version": header.get("version", datetime.fromtimestamp(modified, timezone.utc).strftime("%Y-%m-%d")),
            "product": header.get("product", ""), "title": header.get("title", stem), "text": body.strip()}


def superseded_by(doc: dict, docs: list[dict]) -> dict | None:
    """The newest document of the same product with a later version, if any."""
    if not doc.get("product"):
        return None
    newer = [d for d in docs if d.get("product") == doc["product"] and d["version"] > doc["version"]]
    return max(newer, key=lambda d: d["version"], default=None)


class VectorCache:
    """Embeddings kept in the session database, so a restart never re-embeds unchanged text."""

    def __init__(self, path: str, model: str):
        self._path, self._model = path, model

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, timeout=5)
        connection.execute("CREATE TABLE IF NOT EXISTS doc_vectors (model TEXT NOT NULL, hash TEXT NOT NULL, "
                           "vector TEXT NOT NULL, PRIMARY KEY (model, hash))")
        return connection

    @staticmethod
    def _key(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def get(self, text: str) -> list[float] | None:
        try:
            connection = self._connect()
            try:
                row = connection.execute("SELECT vector FROM doc_vectors WHERE model = ? AND hash = ?",
                                         (self._model, self._key(text))).fetchone()
            finally:
                connection.close()
            return json.loads(row[0]) if row else None
        except (sqlite3.Error, ValueError):
            return None

    def put(self, text: str, vector: list[float]) -> None:
        try:
            connection = self._connect()
            try:
                with connection:
                    connection.execute("INSERT OR REPLACE INTO doc_vectors VALUES (?, ?, ?)",
                                       (self._model, self._key(text), json.dumps(list(vector))))
            finally:
                connection.close()
        except sqlite3.Error:
            pass  # A cache that cannot be written only costs time.


class DocLibrary:
    def __init__(self, folder: str | None, embedding, creator_id: str = "default",
                 cache_path: str | None = None, model: str | None = None):
        self.folder = folder or None
        self.embedding = embedding
        self.creator_id = creator_id
        self.model = model or getattr(embedding, "model", "embedding")
        self.index = LocalVectorIndex(embedding)
        self._cache = VectorCache(cache_path, self.model) if cache_path else None
        self._lock = threading.RLock()
        self._worker: threading.Thread | None = None
        self._docs: dict[str, dict] = {}  # file name -> parsed document, once indexed
        self._seen: dict[str, tuple] = {}  # file name -> fingerprint of what was indexed
        self._error: str | None = None
        self._retry_at = 0.0
        self._notices: list[str] = []

    # Folder scan and background indexing

    @property
    def enabled(self) -> bool:
        return self.folder is not None

    def _scan(self) -> dict[str, tuple]:
        if not self.enabled or not os.path.isdir(self.folder):
            return {}
        found = {}
        with os.scandir(self.folder) as entries:
            for entry in entries:
                if (entry.name.lower().endswith(TYPES) and not entry.name.startswith(".")
                        and entry.name.lower() != "readme.md" and entry.is_file(follow_symlinks=False)):
                    info = entry.stat(follow_symlinks=False)
                    found[entry.name] = (info.st_size, info.st_mtime_ns)
        return found

    def sync(self, wait: bool = False) -> None:
        """Index what changed since the last look; returns at once unless `wait`."""
        if not self.enabled:
            return
        with self._lock:
            busy = self._worker is not None and self._worker.is_alive()
            if not busy and (self._scan() != self._seen) and monotonic() >= self._retry_at:
                self._worker = threading.Thread(target=self._run, daemon=True)
                self._worker.start()
            worker = self._worker
        if wait and worker is not None:
            worker.join()

    def _run(self) -> None:
        indexed = 0
        while True:
            scan = self._scan()
            with self._lock:
                removed = [name for name in self._seen if name not in scan]
                changed = [name for name, fingerprint in scan.items() if self._seen.get(name) != fingerprint]
                for name in removed:
                    doc = self._docs.pop(name, None)
                    if doc is not None:
                        self.index.invalidate_source(self.creator_id, doc["source"])
                    del self._seen[name]
            if not changed:
                break
            for name in sorted(changed):  # A fixed order, so a clashing source name is stable.
                try:
                    self._index_file(name, scan[name])
                except LLMError as error:
                    self._fail(error)
                    return
                indexed += 1
        with self._lock:
            self._error = None
            if indexed:
                self._notices.append(f"Document search: {indexed} document{'s' if indexed != 1 else ''} indexed.")

    def _read(self, name: str, fingerprint: tuple) -> dict | None:
        try:
            with open(os.path.join(self.folder, name), encoding="utf-8") as f:
                text = f.read()
        except (OSError, UnicodeDecodeError):
            with self._lock:
                self._notices.append(f"warning: skipped {name}: not readable UTF-8 text")
            return None
        return parse_document(name, text, fingerprint[1] / 1e9)

    def _embed(self, text: str) -> list[float]:
        vector = self._cache.get(text) if self._cache else None
        if vector is None:
            vector = list(self.embedding.embed(text))
            if self._cache:
                self._cache.put(text, vector)
        return vector

    def _index_file(self, name: str, fingerprint: tuple) -> None:
        doc = self._read(name, fingerprint)
        if doc is None:
            with self._lock:
                self._seen[name] = fingerprint  # Unreadable: not retried until the file changes.
            return
        chunks = chunk_text(doc["text"])
        vectors = [self._embed(chunk) for chunk in chunks]  # The slow part, outside the lock.
        with self._lock:
            taken = {d["source"] for other, d in self._docs.items() if other != name}
            while doc["source"] in taken:
                doc["source"] += "-" + name.rsplit(".", 1)[0]
            old = self._docs.get(name)
            if old is not None and old["source"] != doc["source"]:
                self.index.invalidate_source(self.creator_id, old["source"])
            self.index.replace_source(self.creator_id, doc["source"], doc["version"],
                                      [IndexChunk(f"{doc['source']}-{i}", chunk, vector)
                                       for i, (chunk, vector) in enumerate(zip(chunks, vectors))])
            doc["chunks"] = len(chunks)
            self._docs[name] = doc
            self._seen[name] = fingerprint

    def explain(self, error: Exception) -> str:
        """The error as a message, with the fix when the embedding model is simply not installed."""
        return str(error) + (f" (run: ollama pull {self.model})" if isinstance(error, ModelNotFoundError) else "")

    def _fail(self, error: Exception) -> None:
        reason = self.explain(error)
        with self._lock:
            if reason != self._error:
                self._notices.append(f"Document search is off: {reason}")
            self._error = reason
            self._retry_at = monotonic() + RETRY_SECONDS

    # What the surfaces show

    def notices(self) -> list[str]:
        with self._lock:
            lines, self._notices = self._notices, []
        return lines

    def ready_count(self) -> int:
        with self._lock:
            return sum(1 for doc in self._docs.values() if doc["chunks"] > 0)

    def status(self) -> dict:
        with self._lock:
            scan = self._scan()
            pending = sum(1 for name, fingerprint in scan.items() if self._seen.get(name) != fingerprint)
            ready = len(self._docs)
            if not self.enabled:
                state = "off"
            elif self._error:
                state = "unavailable"
            elif pending or (self._worker is not None and self._worker.is_alive()):
                state = "indexing"
            else:
                state = "ready" if ready else "empty"
            return {"state": state, "folder": self.folder, "embed_model": self.model, "documents": ready,
                    "pending": pending, "error": self._error}

    def documents(self) -> list[dict]:
        with self._lock:
            scan = self._scan()
            out = []
            for name in sorted(scan):
                doc = self._docs.get(name)
                ready = doc is not None and self._seen.get(name) == scan[name]
                out.append({"name": name, "bytes": scan[name][0], "state": "ready" if ready else "pending",
                            **({"source": doc["source"], "version": doc["version"], "title": doc["title"],
                                "product": doc["product"], "chunks": doc["chunks"]} if doc else {})})
            return out

    def metadata(self) -> list[dict]:
        with self._lock:
            return list(self._docs.values())

    # Searching

    def search(self, query: str, limit: int = 3):
        self.sync()
        with self._lock:
            return self.index.for_brand(self.creator_id).search(query, limit)

    # Adding and removing

    def _total(self, skip: str | None = None) -> int:
        return sum(size for name, (size, _) in self._scan().items() if name != skip)

    @staticmethod
    def check_name(name: object) -> str:
        if not isinstance(name, str) or not NAME.match(name):
            raise DocError("Use letters, digits, dots, dashes and underscores in the file name (no folders).")
        if not name.lower().endswith(TYPES) or name.lower() == "readme.md":
            raise DocError(f"Only {' and '.join(TYPES)} documents can be added (and not README.md).")
        return name

    def put(self, name: object, text: object) -> str:
        """Write a document into the folder and index it. Returns "added" or "updated"."""
        name = self.check_name(name)
        if not isinstance(text, str):
            raise DocError("The document must be text.")
        data = text.encode("utf-8", "surrogatepass")
        if b"\x00" in data:
            raise DocError(f"{name} does not look like a text file.")
        if len(data) > MAX_FILE_BYTES:
            raise DocError(f"{name} is larger than {MAX_FILE_BYTES // 2**20} MB.")
        if self._total(skip=name) + len(data) > MAX_TOTAL_BYTES:
            raise DocError(f"The documents folder can hold {MAX_TOTAL_BYTES // 2**20} MB in total.")
        if not self.enabled:
            raise DocError("Document search is switched off (SENSAI_DOCS is empty).")
        target = os.path.join(self.folder, name)
        existed = os.path.isfile(target)
        try:
            os.makedirs(self.folder, exist_ok=True)
            if os.path.islink(target) or (os.path.exists(target) and not existed):
                raise DocError(f"{name} is taken by something that is not a plain file.")
            fd, temporary = tempfile.mkstemp(dir=self.folder, prefix=".upload-")
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(data)
                os.replace(temporary, target)
            except BaseException:
                try:
                    os.remove(temporary)
                except OSError:
                    pass
                raise
        except OSError as error:
            raise DocError(f"Cannot write to the documents folder: {error.strerror or error}") from None
        self.sync()
        return "updated" if existed else "added"

    def add_file(self, path: str) -> tuple[str, str]:
        """Copy a file from anywhere on this computer into the folder: (name, "added" | "updated")."""
        path = os.path.expanduser(path)
        if not os.path.isfile(path):
            raise DocError(f"{path}: no such file.")
        name = re.sub(r"[^A-Za-z0-9._-]+", "-", os.path.basename(path)).strip("-.")
        self.check_name(name)
        try:
            with open(path, "rb") as f:
                data = f.read(MAX_FILE_BYTES + 1)
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            raise DocError(f"{path} is not UTF-8 text.") from None
        except OSError as error:
            raise DocError(f"{path}: {error.strerror or error}") from None
        return name, self.put(name, text)

    def remove(self, name: object) -> None:
        name = self.check_name(name)
        target = os.path.join(self.folder or DEFAULT_FOLDER, name)
        if not self.enabled or os.path.islink(target) or not os.path.isfile(target):
            raise DocError(f"No document named {name}.")
        try:
            os.remove(target)
        except OSError as error:
            raise DocError(f"Cannot remove {name}: {error.strerror or error}") from None
        self.sync(wait=True)

    def reindex(self) -> None:
        """Forget the index and read everything again (the vector cache keeps it cheap)."""
        with self._lock:
            for doc in self._docs.values():
                self.index.invalidate_source(self.creator_id, doc["source"])
            self._docs.clear()
            self._seen.clear()
            self._retry_at = 0.0
            self._error = None
        self.sync(wait=True)


def search_with_hits(library: DocLibrary, query: str, limit: int = 3) -> tuple[str, list[dict]]:
    """The tool's answer text, and the hits behind it (source, version, score, outdated)."""
    results = library.search(query, limit)
    docs = library.metadata()
    pending = library.status()["pending"]
    note = f"\n({pending} more document{'s are' if pending != 1 else ' is'} still being indexed.)" if pending else ""
    if not results:
        return "No relevant documents found" + note, []
    lines, hits = [], []
    for n, hit in enumerate(results, 1):
        doc = next((d for d in docs if d["source"] == hit.source), None)
        label = f"{hit.source}, {doc['version'] if doc else ''}"
        newer = superseded_by(doc, docs) if doc else None
        if newer:
            label += f", OUTDATED: superseded by {newer['source']} {newer['version']}"
        lines.append(f"[{label}] {hit.text}")
        hits.append({"n": n, "source": hit.source, "version": doc["version"] if doc else "", "score": round(hit.score, 3),
                     "outdated": newer is not None, "text": hit.text})
    return "\n".join(lines) + note, hits


def search_docs_handler(arguments: dict, cancellation, *, library: DocLibrary) -> ToolResult:
    return ToolResult(output=search_with_hits(library, arguments.get("query", ""))[0])


# The slash commands: each returns the lines to print.

def _paths(argument: str) -> list[str]:
    """Quoted or escaped paths split like a shell; a bare path with spaces in it stays one path."""
    whole = argument.strip()
    if os.path.exists(os.path.expanduser(whole)):
        return [whole]
    try:
        return shlex.split(argument)
    except ValueError:
        return [whole]


def add_command(library: DocLibrary, argument: str) -> list[str]:
    """`/add <path...>`: a file or a folder (its .md and .txt files) from anywhere."""
    paths = _paths(argument)
    if not paths:
        return ["usage: /add <file or folder> [...]"]
    lines = []
    for path in paths:
        full = os.path.expanduser(path)
        files = ([os.path.join(full, name) for name in sorted(os.listdir(full))
                  if name.lower().endswith(TYPES) and name.lower() != "readme.md"]
                 if os.path.isdir(full) else [full])
        if os.path.isdir(full) and not files:
            lines.append(f"{path}: no .md or .txt files in that folder.")
        for file in files:
            try:
                name, outcome = library.add_file(file)
                lines.append(f"{outcome.capitalize()} {name}.")
            except DocError as error:
                lines.append(f"error: {error}")
    return lines + ["Indexing in the background; /docs shows progress."] if any(
        line.startswith(("Added", "Updated")) for line in lines) else lines


def remove_command(library: DocLibrary, argument: str) -> list[str]:
    if not argument.strip():
        return ["usage: /remove <document name>"]
    try:
        library.remove(argument.strip())
    except DocError as error:
        return [f"error: {error}"]
    return [f"Removed {argument.strip()}."]


def docs_command(library: DocLibrary, argument: str = "") -> list[str]:
    """`/docs`: the documents and the search status; `/docs <text>`: what a search finds."""
    library.sync()
    if not argument.strip():
        status = library.status()
        lines = [f"{d['name']}   {d.get('version', '-')}   "
                 f"{str(d['chunks']) + ' chunks' if d['state'] == 'ready' else 'indexing'}"
                 for d in library.documents()]
        header = {"off": "Document search is off.", "empty": f"No documents yet. /add a file, or copy files into {library.folder}.",
                  "indexing": f"Indexing {status['pending']} document(s)...", "ready": f"{status['documents']} documents ready.",
                  "unavailable": f"Document search is off: {status['error']}"}[status["state"]]
        return [header] + lines
    try:
        results = library.search(argument.strip(), 3)
    except (LLMError, VectorIndexError) as error:
        return [f"error: {library.explain(error)}"]
    return [f"[{i}] {hit.source} · score {hit.score:.2f}\n    {hit.text[:120]}"
            for i, hit in enumerate(results, 1)] or ["No relevant documents found"]


def reindex_command(library: DocLibrary) -> list[str]:
    library.reindex()
    status = library.status()
    if status["state"] == "unavailable":
        return [f"error: {status['error']}"]
    return [f"Reindexed {status['documents']} documents ({len(library.index.entries(library.creator_id))} chunks)."]


__all__ = ["DOCS_PROMPT", "SEARCH_DOCS", "DocError", "DocLibrary", "add_command", "docs_command", "remove_command",
           "reindex_command", "search_docs_handler", "search_with_hits"]
