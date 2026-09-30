from unittest.mock import Mock, patch

import pytest
import requests

from sensai.contracts import EmbeddingPort
from sensai.errors import LLMConnectionError, LLMError, ModelNotFoundError, SensaiError
from sensai.llm.embeddings import (
    EmbeddingDimensionError,
    EmbeddingError,
    EmbeddingResponseError,
    OllamaEmbeddingAdapter,
)

POST = "sensai.llm.embeddings.requests.post"


def response(body=None, status=200):
    return Mock(status_code=status, json=Mock(return_value=body))


def test_direct_request_and_contract():
    adapter = OllamaEmbeddingAdapter("embed-model", "localhost:11434/", timeout=3)
    assert isinstance(adapter, EmbeddingPort)
    resp = response({"embeddings": [[3, 4]]})
    with patch(POST, return_value=resp) as post:
        assert adapter.embed("a private input") == (3.0, 4.0)
    resp.close.assert_called_once_with()
    post.assert_called_once_with(
        "http://localhost:11434/api/embed",
        json={"model": "embed-model", "input": "a private input"},
        timeout=3,
    )
    assert adapter.dimensions == 2


def test_dimensions_stick_after_first_success_and_failed_response_does_not_change_them():
    adapter = OllamaEmbeddingAdapter("m")
    responses = [
        response({"embeddings": [[1, 0]]}),
        response({"embeddings": [[1, 2, 3]]}),
        response({"embeddings": [[0, 1]]}),
    ]
    with patch(POST, side_effect=responses):
        assert adapter.embed("first") == (1.0, 0.0)
        with pytest.raises(EmbeddingDimensionError):
            adapter.embed("second")
        assert adapter.dimensions == 2
        assert adapter.embed("third") == (0.0, 1.0)
    for resp in responses:
        resp.close.assert_called_once_with()


def test_pinned_dimensions_fail_without_ever_changing():
    adapter = OllamaEmbeddingAdapter("m", dimensions=3)
    resp = response({"embeddings": [[1, 2]]})
    with patch(POST, return_value=resp):
        with pytest.raises(EmbeddingDimensionError):
            adapter.embed("text")
    assert adapter.dimensions == 3
    resp.close.assert_called_once_with()


@pytest.mark.parametrize(
    "body",
    [
        None, {}, [], {"embeddings": []}, {"embeddings": [[1], [2]]},
        {"embeddings": [None]}, {"embeddings": [[]]},
        {"embeddings": [[0, 0]]}, {"embeddings": [[True, 1]]},
        {"embeddings": [["1", 2]]}, {"embeddings": [[None, 1]]},
        {"embeddings": [[float("nan"), 1]]},
        {"embeddings": [[float("inf"), 1]]},
        {"embeddings": [[1.5e308, 1.5e308]]},
        {"embeddings": [[10**400]]},
    ],
)
def test_rejects_malformed_or_unusable_embeddings(body):
    resp = response(body)
    with patch(POST, return_value=resp):
        with pytest.raises(EmbeddingResponseError):
            OllamaEmbeddingAdapter("m").embed("text")
    resp.close.assert_called_once_with()


def test_invalid_json():
    resp = Mock(status_code=200, json=Mock(side_effect=ValueError))
    with patch(POST, return_value=resp):
        with pytest.raises(EmbeddingResponseError):
            OllamaEmbeddingAdapter("m").embed("text")
    resp.close.assert_called_once_with()


@pytest.mark.parametrize(
    ("status", "error"),
    [(404, ModelNotFoundError), (400, EmbeddingError), (429, EmbeddingError),
     (503, EmbeddingError)],
)
def test_http_errors_are_typed_and_do_not_echo_response(status, error):
    private = "private text from server"
    resp = response({"error": private}, status)
    with patch(POST, return_value=resp):
        with pytest.raises(error) as caught:
            OllamaEmbeddingAdapter("m").embed(private)
    assert isinstance(caught.value, SensaiError)
    assert private not in str(caught.value)
    resp.close.assert_called_once_with()
    resp.json.assert_not_called()


def test_close_failure_is_typed_and_does_not_pin_dimensions():
    adapter = OllamaEmbeddingAdapter("m")
    resp = response({"embeddings": [[1, 0]]})
    resp.close.side_effect = OSError("secret response")
    with patch(POST, return_value=resp):
        with pytest.raises(EmbeddingError) as caught:
            adapter.embed("sensitive input")
    assert "secret response" not in str(caught.value)
    assert "sensitive input" not in str(caught.value)
    assert adapter.dimensions is None
    resp.close.assert_called_once_with()


def test_close_failure_preserves_primary_embedding_error():
    resp = response({"embeddings": []})
    resp.close.side_effect = OSError("secret close detail")
    with patch(POST, return_value=resp):
        with pytest.raises(EmbeddingResponseError, match="expected one Ollama embedding") as caught:
            OllamaEmbeddingAdapter("m").embed("private input")
    assert "secret" not in str(caught.value)
    assert "private" not in str(caught.value)
    if hasattr(caught.value, "add_note"):
        assert caught.value.__notes__ == ["Ollama embedding response close failed"]
    resp.close.assert_called_once_with()


@pytest.mark.parametrize(
    ("failure", "error"),
    [(requests.ConnectionError("secret"), LLMConnectionError),
     (requests.Timeout("secret"), EmbeddingError),
     (requests.RequestException("secret"), EmbeddingError)],
)
def test_transport_errors_do_not_echo_request_or_raw_exception(failure, error):
    with patch(POST, side_effect=failure):
        with pytest.raises(error) as caught:
            OllamaEmbeddingAdapter("m").embed("sensitive input")
    assert isinstance(caught.value, LLMError)
    assert "secret" not in str(caught.value)
    assert "sensitive input" not in str(caught.value)


@pytest.mark.parametrize("text", ["", " \t ", None])
def test_empty_input_never_calls_network(text):
    with patch(POST) as post:
        with pytest.raises(EmbeddingError):
            OllamaEmbeddingAdapter("m").embed(text)
    post.assert_not_called()


@pytest.mark.parametrize(
    "kwargs",
    [{"model": ""}, {"model": "m", "timeout": 0},
     {"model": "m", "timeout": float("nan")},
     {"model": "m", "dimensions": 0}, {"model": "m", "dimensions": True}],
)
def test_invalid_configuration(kwargs):
    with pytest.raises(ValueError):
        OllamaEmbeddingAdapter(**kwargs)
