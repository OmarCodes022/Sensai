"""Ollama backend."""
from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from sys import exc_info
from time import perf_counter
from typing import TYPE_CHECKING

import requests
from pydantic import ValidationError

from sensai.core.errors import LLMConnectionError, LLMError, ModelNotFoundError
from sensai.llm.base import LLMClient
from sensai.llm.schemas import ChatChunk, ChatRequest, OllamaUsage, UsageError
from sensai.core.messages import Message

if TYPE_CHECKING:
    from sensai.core.contracts import EventPort


class _ResponseError(LLMError):
    def __init__(self, message: str, code: UsageError):
        super().__init__(message)
        self.code = code


class OllamaClient(LLMClient):
    def __init__(
        self,
        host: str = "http://localhost:11434",
        timeout: float = 60.0,
        event_sink: EventPort | None = None,
        usage_sink: Callable[[OllamaUsage], None] | None = None,
    ):
        self.host = host if "://" in host else f"http://{host}"
        self.timeout = timeout
        self._telemetry = None
        if event_sink is not None:
            from sensai.observability.telemetry import Telemetry

            self._telemetry = Telemetry(event_sink)
        self._usage_sink = usage_sink

    def stream(self, model: str, messages: Sequence[Message]) -> Iterator[str]:
        body = ChatRequest(model=model, messages=list(messages)).model_dump(mode="json")
        started = perf_counter()
        operation_id = None
        if self._telemetry is not None:
            from sensai.observability.telemetry import new_operation_id

            operation_id = new_operation_id()
            self._telemetry.request_started(operation_id)
        resp = None
        reported = False

        def close_response() -> None:
            nonlocal resp
            if resp is None:
                return
            closing, resp = resp, None
            try:
                close = getattr(closing, "close", None)
                if callable(close):
                    close()
            except Exception:
                raise _ResponseError(
                    "failed to close Ollama response", UsageError.TRANSPORT
                ) from None

        def report(
            error: UsageError | None = None, final: ChatChunk | None = None
        ) -> None:
            nonlocal reported
            reported = True
            usage = OllamaUsage(
                prompt_tokens=final.prompt_eval_count if final is not None else None,
                output_tokens=final.eval_count if final is not None else None,
                latency_ms=(perf_counter() - started) * 1000,
                error=error,
                server_duration_ms=(
                    final.total_duration / 1_000_000
                    if final is not None and final.total_duration is not None
                    else None
                ),
            )
            if self._usage_sink is not None:
                self._usage_sink(usage)
            if self._telemetry is not None:
                self._telemetry.request_finished(operation_id, usage)

        try:
            resp = requests.post(
                f"{self.host}/api/chat", json=body, stream=True, timeout=self.timeout
            )
            self._check(resp, model)
            for line in resp.iter_lines():
                if not line:
                    continue
                chunk = self._parse(line)
                if chunk.message and chunk.message.content:
                    yield chunk.message.content
                if chunk.done:
                    close_response()
                    report(final=chunk)
                    return
            raise _ResponseError(
                "incomplete response from Ollama", UsageError.INCOMPLETE_STREAM
            )
        except GeneratorExit:
            if not reported:
                try:
                    close_response()
                except _ResponseError:
                    report(error=UsageError.TRANSPORT)
                    raise
                report(error=UsageError.CANCELLED)
            raise
        except requests.ConnectionError:
            if not reported:
                report(error=UsageError.CONNECTION)
            raise LLMConnectionError(
                "cannot reach Ollama, is it running? try: ollama serve"
            ) from None
        except requests.Timeout:
            if not reported:
                report(error=UsageError.TIMEOUT)
            raise LLMError("Ollama timed out") from None
        except requests.RequestException:
            if not reported:
                report(error=UsageError.TRANSPORT)
            raise LLMError("request to Ollama failed") from None
        except ModelNotFoundError:
            if not reported:
                report(error=UsageError.MODEL_NOT_FOUND)
            raise
        except _ResponseError as exc:
            if not reported:
                report(error=exc.code)
            raise
        except Exception:
            if reported:
                raise
            report(error=UsageError.TRANSPORT)
            raise LLMError("Ollama stream failed") from None
        finally:
            if resp is not None:
                primary = exc_info()[1]
                try:
                    close_response()
                except _ResponseError:
                    if primary is None:
                        raise
                    if hasattr(primary, "add_note"):
                        primary.add_note("Ollama response close failed")

    @staticmethod
    def _check(resp, model: str) -> None:
        if resp.status_code == 404:
            raise ModelNotFoundError(
                f"model '{model}' not found, try: ollama pull {model}"
            )
        if resp.status_code >= 400:
            raise _ResponseError("Ollama rejected the request", UsageError.HTTP)

    @staticmethod
    def _parse(line: bytes) -> ChatChunk:
        try:
            chunk = ChatChunk.model_validate_json(line)
        except ValidationError:
            raise _ResponseError(
                "invalid response from Ollama", UsageError.INVALID_RESPONSE
            ) from None
        if chunk.error:
            raise _ResponseError("Ollama stream reported an error", UsageError.REMOTE)
        return chunk
