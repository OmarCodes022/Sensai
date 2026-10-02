"""Schema-constrained, non-streaming Ollama chat responses."""

import json
from collections.abc import Sequence
from sys import exc_info
from typing import TypeVar

import requests
from pydantic import BaseModel, ValidationError

from sensai.core.errors import LLMConnectionError, LLMError, ModelNotFoundError
from sensai.core.messages import Message

T = TypeVar("T", bound=BaseModel)


def _reject_non_json_constant(value: str) -> None:
    raise ValueError("invalid JSON constant")


class StructuredOutputError(LLMError):
    """The Ollama reply is missing or fails JSON or schema validation."""


class OllamaStructuredClient:
    def __init__(self, host: str = "http://localhost:11434", timeout: float = 60.0):
        self.host = host if "://" in host else f"http://{host}"
        self.timeout = timeout

    def complete(
        self, model: str, messages: Sequence[Message], schema: type[T]
    ) -> T:
        """Return a validated model, or raise LLMError on transport/output failure."""
        if not isinstance(schema, type) or not issubclass(schema, BaseModel):
            raise TypeError("schema must be a Pydantic model class")

        body = {
            "model": model,
            "messages": [message.model_dump(mode="json") for message in messages],
            "format": schema.model_json_schema(),
            "stream": False,
        }
        try:
            response = requests.post(
                f"{self.host}/api/chat", json=body, stream=False, timeout=self.timeout
            )
        except requests.ConnectionError:
            raise LLMConnectionError(
                f"cannot reach Ollama at {self.host}, is it running? try: ollama serve"
            ) from None
        except requests.Timeout:
            raise LLMError(f"Ollama at {self.host} timed out") from None
        except requests.RequestException:
            raise LLMError("request to Ollama failed") from None

        try:
            if response.status_code == 404:
                raise ModelNotFoundError(
                    f"model '{model}' not found, try: ollama pull {model}"
                )
            if response.status_code >= 400:
                raise LLMError(f"Ollama rejected the request (HTTP {response.status_code})")
            try:
                payload = response.json()
            except ValueError:
                raise StructuredOutputError("invalid JSON response from Ollama") from None
            if not isinstance(payload, dict):
                raise StructuredOutputError("invalid JSON response from Ollama")
            if payload.get("error") is not None:
                raise LLMError("Ollama returned an error")
            message = payload.get("message")
            if not isinstance(message, dict):
                raise StructuredOutputError("missing message in Ollama response")
            content = message.get("content")
            if content is None:
                raise StructuredOutputError("missing content in Ollama response")
            if not isinstance(content, str):
                raise StructuredOutputError("invalid content in Ollama response")
            if not content.strip():
                raise StructuredOutputError("empty content in Ollama response")
            try:
                json.loads(content, parse_constant=_reject_non_json_constant)
            except ValueError:
                raise StructuredOutputError("invalid JSON content from Ollama") from None
            try:
                return schema.model_validate_json(content, strict=True)
            except ValidationError:
                raise StructuredOutputError(
                    f"JSON content does not match {schema.__name__} schema"
                ) from None
        except requests.ConnectionError:
            raise LLMConnectionError(f"connection to Ollama at {self.host} failed") from None
        except requests.Timeout:
            raise LLMError(f"Ollama at {self.host} timed out") from None
        except requests.RequestException:
            raise LLMError("request to Ollama failed") from None
        finally:
            primary = exc_info()[1]
            try:
                response.close()
            except Exception:
                if primary is not None:
                    if hasattr(primary, "add_note"):
                        primary.add_note("Ollama structured response close failed")
                else:
                    raise LLMError("failed to close Ollama structured response") from None
