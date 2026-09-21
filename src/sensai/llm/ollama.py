"""Ollama backend."""
from collections.abc import Iterator, Sequence

import requests
from pydantic import ValidationError

from sensai.errors import LLMConnectionError, LLMError, ModelNotFoundError
from sensai.llm.base import LLMClient
from sensai.llm.schemas import ChatChunk, ChatRequest
from sensai.messages import Message


class OllamaClient(LLMClient):
    def __init__(self, host: str = "http://localhost:11434", timeout: float = 60.0):
        self.host = host if "://" in host else f"http://{host}"
        self.timeout = timeout

    def stream(self, model: str, messages: Sequence[Message]) -> Iterator[str]:
        body = ChatRequest(model=model, messages=list(messages)).model_dump(mode="json")
        try:
            resp = requests.post(
                f"{self.host}/api/chat", json=body, stream=True, timeout=self.timeout
            )
            self._check(resp, model)
            for line in resp.iter_lines():
                if line and (text := self._parse(line)):
                    yield text
        except requests.ConnectionError as e:
            raise LLMConnectionError(
                f"cannot reach Ollama at {self.host}, is it running? try: ollama serve"
            ) from e
        except requests.Timeout as e:
            raise LLMError(f"Ollama at {self.host} timed out") from e
        except requests.RequestException as e:
            raise LLMError(f"request to Ollama failed: {e}") from e

    @staticmethod
    def _check(resp, model: str) -> None:
        if resp.status_code == 404:
            raise ModelNotFoundError(f"model '{model}' not found, try: ollama pull {model}")
        if resp.status_code >= 400:
            try:
                detail = resp.json()["error"]
            except (ValueError, KeyError, TypeError):
                detail = f"HTTP {resp.status_code}"
            raise LLMError(f"Ollama rejected the request: {detail}")

    @staticmethod
    def _parse(line: bytes) -> str:
        try:
            chunk = ChatChunk.model_validate_json(line)
        except ValidationError as e:
            raise LLMError("invalid response from Ollama") from e
        if chunk.error:
            raise LLMError(chunk.error)
        return chunk.message.content if chunk.message else ""
