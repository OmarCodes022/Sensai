"""Is Ollama up, and is the model installed? Answered from /api/tags, cached for a few seconds."""
from threading import Lock
from time import monotonic

import requests

CACHE_SECONDS = 3.0
TIMEOUT_SECONDS = 2.0


def fetch_tags(host: str) -> tuple[bool, float, list[str]]:
    """(reachable, latency in ms, installed model names)."""
    started = monotonic()
    try:
        response = requests.get(f"{host}/api/tags", timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
        names = [entry["name"] for entry in response.json().get("models", []) if "name" in entry]
    except (requests.RequestException, ValueError, AttributeError, TypeError):
        return False, 0.0, []
    return True, (monotonic() - started) * 1000, names


def installed(model: str, names: list[str]) -> bool:
    return model in names or (":" not in model and f"{model}:latest" in names)


class Health:
    def __init__(self, host: str, model: str, fetch=fetch_tags, clock=monotonic):
        self._host = host if "://" in host else f"http://{host}"
        self._model = model
        self._fetch = fetch
        self._clock = clock
        self._lock = Lock()
        self._at = -CACHE_SECONDS
        self._value: tuple[bool, float, list[str]] = (False, 0.0, [])

    def check(self) -> dict:
        with self._lock:
            if self._clock() - self._at >= CACHE_SECONDS:
                self._value, self._at = self._fetch(self._host), self._clock()
            reachable, latency, names = self._value
        return {"ollama": {"reachable": reachable, "host": self._host, "latency_ms": round(latency)},
                "model": {"name": self._model, "available": reachable and installed(self._model, names)}}
