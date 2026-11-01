"""A6: a semantic cache. The first question of a session that closely matches an earlier one, asked with
the same creator, model and system prompt (persona and profile included), gets the saved answer at once.

Questions are compared by the cosine similarity of their embeddings. The file keeps questions and
answers in plain text, like the session database, and stays out of git.
"""
import hashlib
import json
import math
import os
import sqlite3
from dataclasses import dataclass

SCHEMA = ("CREATE TABLE IF NOT EXISTS answers (scope TEXT NOT NULL, question TEXT NOT NULL, "
          "vector TEXT NOT NULL, answer TEXT NOT NULL)")


@dataclass(frozen=True)
class Hit:
    answer: str
    question: str
    similarity: float

    def label(self) -> str:
        return f"from cache · {self.similarity:.0%} similar to \"{self.question}\""


def scope(creator: str, model: str, system_prompt: str) -> str:
    """Changing the creator, the model, the persona or the profile changes the system prompt or the model: a miss."""
    return hashlib.sha256("\0".join((creator, model, system_prompt)).encode("utf-8")).hexdigest()


def _unit(vector) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


class SemanticCache:
    """`embed(text)` gives a vector; any error it raises turns the cache off (`off` says why) instead of failing."""

    def __init__(self, path: str, embed, threshold: float = 0.92):
        self.path, self.embed, self.threshold, self.off = path, embed, threshold, ""

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=5)
        connection.execute(SCHEMA)
        return connection

    def _vector(self, text: str) -> list[float] | None:
        if self.off:
            return None
        try:
            return _unit(self.embed(text))
        except Exception as exc:  # A missing embedding model or Ollama down: the chat goes on without the cache.
            self.off = f"the cache is off for this session ({exc})"
            return None

    def lookup(self, scope_id: str, question: str) -> Hit | None:
        vector = self._vector(question)
        if vector is None:
            return None
        with self._connect() as connection:
            rows = connection.execute("SELECT question, vector, answer FROM answers WHERE scope = ?", (scope_id,)).fetchall()
        best = max(((sum(a * b for a, b in zip(vector, json.loads(v))), q, answer) for q, v, answer in rows), default=None)
        return Hit(best[2], best[1], best[0]) if best and best[0] >= self.threshold else None

    def store(self, scope_id: str, question: str, answer: str) -> None:
        vector = self._vector(question)
        if vector is None or not answer.strip():
            return
        with self._connect() as connection:
            connection.execute("INSERT INTO answers VALUES (?, ?, ?, ?)", (scope_id, question, json.dumps(vector), answer))

    def clear(self) -> int:
        if not os.path.exists(self.path):  # Nothing cached: no empty file is created.
            return 0
        with self._connect() as connection:
            return connection.execute("DELETE FROM answers").rowcount
