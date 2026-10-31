"""Token and latency figures Ollama reported for the requests of one turn."""
from threading import Lock

from sensai.llm.ollama_api import OllamaUsage


class UsageCollector:
    """Usage sink for the chat client; failed attempts report no figures and are ignored."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._items: list[OllamaUsage] = []

    def add(self, usage: OllamaUsage) -> None:
        if usage.error is None:
            with self._lock:
                self._items.append(usage)

    def reset(self) -> None:
        with self._lock:
            self._items.clear()

    def summary(self) -> dict:
        """prompt_tokens is the last request's (the context size); the others add up over tool rounds."""
        with self._lock:
            items = list(self._items)

        def total(values):
            return sum(values) if values and all(v is not None for v in values) else None

        return {
            "prompt_tokens": items[-1].prompt_tokens if items else None,
            "output_tokens": total([u.output_tokens for u in items]),
            "latency_ms": round(sum(u.latency_ms for u in items)) if items else None,
            "server_duration_ms": total([u.server_duration_ms for u in items]),
        }
