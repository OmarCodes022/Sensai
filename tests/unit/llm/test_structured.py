import json
from unittest.mock import patch

import pytest
import requests
from pydantic import BaseModel

from sensai.core.errors import LLMConnectionError, LLMError, ModelNotFoundError
from sensai.llm.structured import OllamaStructuredClient, StructuredOutputError
from sensai.core.messages import Message

POST = "sensai.llm.structured.requests.post"
MESSAGES = (
    Message(role="system", content="Return a short label."),
    Message(role="user", content="Classify this."),
)


class Label(BaseModel):
    name: str
    confidence: float


class Response:
    def __init__(self, body=None, status=200, error=None, close_error=None):
        self.body = body
        self.status_code = status
        self.error = error
        self.close_error = close_error
        self.closed = False

    def json(self):
        if self.error:
            raise self.error
        return self.body

    def close(self):
        self.closed = True
        if self.close_error:
            raise self.close_error


def reply(content):
    return Response({"message": {"role": "assistant", "content": content}, "done": True})


def test_valid_reply_uses_model_schema_and_non_streaming_http():
    response = reply('{"name":"task","confidence":0.8}')
    with patch(POST, return_value=response) as post:
        result = OllamaStructuredClient("localhost:11434", timeout=4).complete(
            "gemma3:1b", MESSAGES, Label
        )

    assert result == Label(name="task", confidence=0.8)
    post.assert_called_once_with(
        "http://localhost:11434/api/chat",
        json={
            "model": "gemma3:1b",
            "messages": [message.model_dump(mode="json") for message in MESSAGES],
            "format": Label.model_json_schema(),
            "stream": False,
        },
        stream=False,
        timeout=4,
    )
    assert response.closed


def test_each_call_selects_its_own_model_and_schema():
    class Priority(BaseModel):
        level: int

    first, second = reply('{"name":"task","confidence":0.8}'), reply('{"level":2}')
    with patch(POST, side_effect=[first, second]) as post:
        client = OllamaStructuredClient()
        assert client.complete("first", MESSAGES, Label).name == "task"
        assert client.complete("second", MESSAGES, Priority).level == 2
    assert [call.kwargs["json"]["model"] for call in post.call_args_list] == [
        "first", "second"
    ]
    assert post.call_args_list[1].kwargs["json"]["format"] == Priority.model_json_schema()
    assert first.closed and second.closed


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (Response(error=json.JSONDecodeError("bad", "x", 0)), "invalid JSON response"),
        (Response(body=[]), "invalid JSON response"),
        (Response(body={"error": "private output"}), "Ollama returned an error"),
        (Response(body={}), "missing message"),
        (Response(body={"message": None}), "missing message"),
        (Response(body={"message": {}}), "missing content"),
        (Response(body={"message": {"content": None}}), "missing content"),
        (Response(body={"message": {"content": ""}}), "empty content"),
        (reply("   "), "empty content"),
        (Response(body={"message": {"content": 123}}), "invalid content"),
        (reply("not json"), "invalid JSON content"),
        (reply('{"name":'), "invalid JSON content"),
        (reply('{"name":"task","confidence":NaN}'), "invalid JSON content"),
        (reply('{"name":"private output"}'), "does not match Label schema"),
        (reply('{"name":"private output","confidence":"0.8"}'), "does not match Label schema"),
        (reply("[]"), "does not match Label schema"),
    ],
)
def test_invalid_responses_raise_without_leaking_values_and_close(response, message):
    with patch(POST, return_value=response):
        with pytest.raises(LLMError, match=message) as exc:
            OllamaStructuredClient().complete("m", MESSAGES, Label)
    assert "private output" not in str(exc.value)
    assert response.closed


@pytest.mark.parametrize(
    ("status", "expected_error", "message"),
    [
        (400, LLMError, "HTTP 400"),
        (404, ModelNotFoundError, "ollama pull m"),
        (503, LLMError, "HTTP 503"),
    ],
)
def test_http_failures_close_the_response(status, expected_error, message):
    response = Response(status=status, body={"error": "private output"})
    with patch(POST, return_value=response):
        with pytest.raises(expected_error, match=message) as exc:
            OllamaStructuredClient().complete("m", MESSAGES, Label)
    assert "private output" not in str(exc.value)
    assert response.closed


@pytest.mark.parametrize(
    ("error", "expected_error", "message"),
    [
        (requests.ConnectionError("private output"), LLMConnectionError, "ollama serve"),
        (requests.Timeout("private output"), LLMError, "timed out"),
        (requests.RequestException("private output"), LLMError, "request to Ollama failed"),
    ],
)
def test_post_failures_have_explicit_safe_errors(error, expected_error, message):
    with patch(POST, side_effect=error):
        with pytest.raises(expected_error, match=message) as exc:
            OllamaStructuredClient().complete("m", MESSAGES, Label)
    assert "private output" not in str(exc.value)


@pytest.mark.parametrize(
    ("error", "expected_error", "message"),
    [
        (requests.ConnectionError(), LLMConnectionError, "connection to Ollama"),
        (requests.Timeout(), LLMError, "timed out"),
        (requests.RequestException(), LLMError, "request to Ollama failed"),
    ],
)
def test_read_failures_close_the_response(error, expected_error, message):
    response = Response(error=error)
    with patch(POST, return_value=response):
        with pytest.raises(expected_error, match=message):
            OllamaStructuredClient().complete("m", MESSAGES, Label)
    assert response.closed


def test_schema_must_be_a_pydantic_model_class_before_post():
    with patch(POST) as post:
        with pytest.raises(TypeError, match="Pydantic model class"):
            OllamaStructuredClient().complete("m", MESSAGES, dict)
    post.assert_not_called()


def test_invalid_json_and_schema_mismatch_have_distinct_errors():
    for content in ("{", '{"confidence":0.8}'):
        with patch(POST, return_value=reply(content)):
            with pytest.raises(StructuredOutputError):
                OllamaStructuredClient().complete("m", MESSAGES, Label)


def test_close_failure_after_valid_response_is_sanitized():
    response = reply('{"name":"task","confidence":0.8}')
    response.close_error = OSError("private close detail")
    with patch(POST, return_value=response):
        with pytest.raises(LLMError, match="failed to close Ollama structured response") as caught:
            OllamaStructuredClient().complete("m", MESSAGES, Label)
    assert "private" not in str(caught.value)
    assert response.closed


def test_close_failure_preserves_primary_schema_error():
    response = reply("invalid json")
    response.close_error = OSError("private close detail")
    with patch(POST, return_value=response):
        with pytest.raises(StructuredOutputError, match="invalid JSON content") as caught:
            OllamaStructuredClient().complete("m", MESSAGES, Label)
    assert "private" not in str(caught.value)
    if hasattr(caught.value, "add_note"):
        assert caught.value.__notes__ == ["Ollama structured response close failed"]
    assert response.closed
