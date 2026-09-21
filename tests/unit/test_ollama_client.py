import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from sensai.errors import LLMConnectionError, LLMError, ModelNotFoundError
from sensai.llm.ollama import OllamaClient
from sensai.messages import Message

MSGS = [Message(role="user", content="hi")]
POST = "sensai.llm.ollama.requests.post"


def fake_response(chunks, status=200, body=None):
    resp = MagicMock(status_code=status)
    resp.json.return_value = body
    resp.iter_lines.return_value = [
        json.dumps({"message": {"role": "assistant", "content": c}, "done": False}).encode()
        for c in chunks
    ] + [json.dumps({"done": True}).encode()]
    return resp


def test_yields_chunks_progressively():
    with patch(POST, return_value=fake_response(["Hel", "lo", "!"])):
        assert list(OllamaClient().stream("m", MSGS)) == ["Hel", "lo", "!"]


def test_request_body_is_streaming_and_serialized():
    with patch(POST, return_value=fake_response(["x"])) as post:
        list(OllamaClient().stream("m", MSGS))
    assert post.call_args.kwargs["json"] == {
        "model": "m",
        "messages": [{"role": "user", "content": "hi"}],
        "stream": True,
    }


def test_host_without_scheme_gets_http():
    assert OllamaClient("localhost:11434").host == "http://localhost:11434"


def test_unknown_model():
    with patch(POST, return_value=fake_response([], status=404)):
        with pytest.raises(ModelNotFoundError, match="ollama pull m"):
            list(OllamaClient().stream("m", MSGS))


def test_bad_request_surfaces_server_message():
    resp = fake_response([], status=400, body={"error": "missing request body"})
    with patch(POST, return_value=resp):
        with pytest.raises(LLMError, match="missing request body"):
            list(OllamaClient().stream("m", MSGS))


def test_connection_failure():
    with patch(POST, side_effect=requests.ConnectionError):
        with pytest.raises(LLMConnectionError, match="ollama serve"):
            list(OllamaClient().stream("m", MSGS))


def test_timeout():
    with patch(POST, side_effect=requests.Timeout):
        with pytest.raises(LLMError, match="timed out"):
            list(OllamaClient().stream("m", MSGS))


def test_error_line_in_stream():
    resp = MagicMock(status_code=200)
    resp.iter_lines.return_value = [b'{"error": "out of memory"}']
    with patch(POST, return_value=resp):
        with pytest.raises(LLMError, match="out of memory"):
            list(OllamaClient().stream("m", MSGS))


def test_garbage_line_in_stream():
    resp = MagicMock(status_code=200)
    resp.iter_lines.return_value = [b"not json"]
    with patch(POST, return_value=resp):
        with pytest.raises(LLMError, match="invalid response"):
            list(OllamaClient().stream("m", MSGS))
