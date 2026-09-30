"""Direct Ollama embedding adapter for the EmbeddingPort boundary."""

import math
from sys import exc_info
from threading import Lock

import requests

from sensai.errors import LLMConnectionError, LLMError, ModelNotFoundError


class EmbeddingError(LLMError):
    """An embedding request or response failed."""


class EmbeddingResponseError(EmbeddingError):
    """Ollama returned an unusable embedding."""


class EmbeddingDimensionError(EmbeddingResponseError):
    """The embedding size changed for this adapter."""


class OllamaEmbeddingAdapter:
    def __init__(
        self,
        model: str,
        host: str = "http://localhost:11434",
        timeout: float = 60.0,
        dimensions: int | None = None,
    ):
        if not isinstance(model, str) or not model.strip():
            raise ValueError("embedding model must not be empty")
        if not isinstance(host, str) or not host.strip():
            raise ValueError("Ollama host must not be empty")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise ValueError("timeout must be positive and finite")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be positive and finite")
        if dimensions is not None and (
            isinstance(dimensions, bool)
            or not isinstance(dimensions, int)
            or dimensions <= 0
        ):
            raise ValueError("dimensions must be a positive integer")
        self.model = model
        self.host = (host if "://" in host else f"http://{host}").rstrip("/")
        self.timeout = timeout
        self._dimensions = dimensions
        self._dimension_lock = Lock()

    @property
    def dimensions(self) -> int | None:
        return self._dimensions

    def embed(self, text: str) -> tuple[float, ...]:
        if not isinstance(text, str) or not text.strip():
            raise EmbeddingError("embedding input must not be empty")
        try:
            response = requests.post(
                f"{self.host}/api/embed",
                json={"model": self.model, "input": text},
                timeout=self.timeout,
            )
        except requests.ConnectionError:
            raise LLMConnectionError("cannot reach Ollama for embeddings") from None
        except requests.Timeout:
            raise EmbeddingError("Ollama embedding request timed out") from None
        except requests.RequestException:
            raise EmbeddingError("Ollama embedding request failed") from None

        try:
            vector = self._read_vector(response)
        finally:
            primary = exc_info()[1]
            try:
                response.close()
            except Exception:
                if primary is not None:
                    if hasattr(primary, "add_note"):
                        primary.add_note("Ollama embedding response close failed")
                else:
                    raise EmbeddingError("failed to close Ollama embedding response") from None
        with self._dimension_lock:
            if self._dimensions is not None and len(vector) != self._dimensions:
                raise EmbeddingDimensionError("Ollama embedding dimension changed")
            self._dimensions = len(vector)
        return vector

    @staticmethod
    def _read_vector(response: requests.Response) -> tuple[float, ...]:
        if response.status_code == 404:
            raise ModelNotFoundError("Ollama embedding model not found")
        if response.status_code >= 400:
            raise EmbeddingError(
                f"Ollama embedding request failed (HTTP {response.status_code})"
            )
        try:
            payload = response.json()
        except (ValueError, requests.RequestException):
            raise EmbeddingResponseError("invalid Ollama embedding response") from None
        if not isinstance(payload, dict):
            raise EmbeddingResponseError("invalid Ollama embedding response")
        vectors = payload.get("embeddings")
        if not isinstance(vectors, list) or len(vectors) != 1:
            raise EmbeddingResponseError("expected one Ollama embedding")
        raw = vectors[0]
        if not isinstance(raw, list) or not raw:
            raise EmbeddingResponseError("invalid Ollama embedding vector")
        if any(
            isinstance(value, bool) or not isinstance(value, (int, float))
            for value in raw
        ):
            raise EmbeddingResponseError("invalid Ollama embedding vector")
        try:
            vector = tuple(float(value) for value in raw)
        except OverflowError:
            raise EmbeddingResponseError("invalid Ollama embedding vector") from None
        if not all(math.isfinite(value) for value in vector):
            raise EmbeddingResponseError("invalid Ollama embedding vector")
        norm = math.hypot(*vector)
        if not math.isfinite(norm) or norm == 0:
            raise EmbeddingResponseError("invalid Ollama embedding vector")
        return vector
