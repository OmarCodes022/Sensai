"""A7: few-shot examples picked for each request. The two example requests closest to the message (cosine
similarity of their embeddings) are sent with their ideal answers as example turns, for that request only.
"""
import json
import math
from importlib.resources import files

from sensai.core.messages import Message

FLOOR = 0.6  # Weaker matches ("hello") get no example.


def _unit(vector) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


class ExamplePicker:
    """`embed(text)` gives a vector; any error turns the picker off (`off` says why) and the chat goes on."""

    def __init__(self, embed, examples: list[dict] | None = None, k: int = 2, floor: float = FLOOR):
        self.embed, self.k, self.floor, self.off = embed, k, floor, ""
        self.examples = examples if examples is not None else json.loads(
            files("sensai.chat").joinpath("examples.json").read_text(encoding="utf-8"))
        self._vectors: list[list[float]] | None = None  # Embedded once, at the first request.

    def pick(self, text: str) -> list[dict]:
        if self.off:
            return []
        try:
            if self._vectors is None:
                self._vectors = [_unit(self.embed(e["request"])) for e in self.examples]
            query = _unit(self.embed(text))
        except Exception as exc:  # A missing embedding model or Ollama down.
            self.off = f"examples are off for this session ({exc})"
            return []
        scored = sorted(((sum(a * b for a, b in zip(query, v)), e) for v, e in zip(self._vectors, self.examples)),
                        key=lambda pair: pair[0], reverse=True)
        return [e for score, e in scored[:self.k] if score >= self.floor]


def turns(examples: list[dict]) -> tuple[Message, ...]:
    """The examples as user/assistant turns, placed right after the system prompt."""
    return tuple(m for e in examples for m in (Message(role="user", content=e["request"]),
                                               Message(role="assistant", content=e["answer"])))
