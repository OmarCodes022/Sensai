"""Reasoning alone is not a visible answer from Ollama."""

from unittest.mock import patch

import pytest

from fakes import ollama_response as response
from sensai.core.errors import LLMError
from sensai.core.messages import Message
from sensai.llm.ollama import OllamaClient
from sensai.llm.ollama_api import UsageError
from sensai.telemetry import BoundedEventSink


@pytest.mark.parametrize("chunks", [
    [{"done": True}],
    [{"message": {"role": "assistant", "content": ""}, "done": True}],
    [{"message": {"role": "assistant", "content": " \t\n"}}, {"done": True}],
    [{"message": {"role": "assistant", "content": "", "thinking": "private reasoning"}},
     {"done": True, "eval_count": 100}],
    [{"message": {"role": "assistant", "content": "", "thinking": "private reasoning"},
      "done": True, "prompt_eval_count": 3, "eval_count": 100}],
])
def test_empty_completion_fails_once_with_sanitized_usage_and_events(chunks):
    received, usages = [], []
    sink = BoundedEventSink(received.append)
    resp = response(*chunks)
    with patch("sensai.llm.ollama.requests.post", return_value=resp):
        with pytest.raises(LLMError, match="no visible answer") as error:
            list(OllamaClient(event_sink=sink, usage_sink=usages.append).stream(
                "model", [Message(role="user", content="private question")]
            ))

    resp.close.assert_called_once()
    assert len(usages) == 1
    assert usages[0].error == UsageError.INVALID_RESPONSE
    assert usages[0].prompt_tokens is None
    assert usages[0].output_tokens is None
    assert sink.drain() == 2
    assert [event.name for event in received] == ["request.started", "request.failed"]
    assert received[1].fields["error_code"] == "invalid_response"
    assert "private" not in repr(received) + str(error.value) + repr(usages)


def test_visible_content_streams_progressively_and_thinking_stays_hidden():
    received, usages = [], []
    sink = BoundedEventSink(received.append)
    resp = response(
        {"message": {"role": "assistant", "content": "", "thinking": "private reasoning"}},
        {"message": {"role": "assistant", "content": "First"}},
        {"message": {"role": "assistant", "content": " last", "thinking": "private reasoning"},
         "done": True, "prompt_eval_count": 4, "eval_count": 2},
    )
    with patch("sensai.llm.ollama.requests.post", return_value=resp) as post:
        stream = OllamaClient(event_sink=sink, usage_sink=usages.append).stream(
            "model", [Message(role="user", content="question")]
        )
        assert next(stream) == "First"
        assert usages == []
        assert next(stream) == " last"
        assert usages == []
        assert list(stream) == []

    assert "think" not in post.call_args.kwargs["json"]
    assert "think" not in post.call_args.kwargs["json"].get("options", {})
    resp.close.assert_called_once()
    assert len(usages) == 1
    assert usages[0].error is None
    assert usages[0].prompt_tokens == 4
    assert usages[0].output_tokens == 2
    assert sink.drain() == 2
    assert [event.name for event in received] == ["request.started", "request.completed"]
    assert "private" not in repr(received)


def test_whitespace_before_visible_done_content_is_preserved():
    resp = response(
        {"message": {"role": "assistant", "content": "\n"}},
        {"message": {"role": "assistant", "content": "Answer"}, "done": True},
    )
    with patch("sensai.llm.ollama.requests.post", return_value=resp):
        assert list(OllamaClient().stream("model", [])) == ["\n", "Answer"]
    resp.close.assert_called_once()


def test_close_failure_preserves_primary_empty_reply_error():
    usages = []
    resp = response({"done": True})
    resp.close.side_effect = OSError("private close detail")
    with patch("sensai.llm.ollama.requests.post", return_value=resp):
        with pytest.raises(LLMError, match="no visible answer") as error:
            list(OllamaClient(usage_sink=usages.append).stream("model", []))
    assert "private" not in str(error.value)
    assert len(usages) == 1
    assert usages[0].error == UsageError.INVALID_RESPONSE
    resp.close.assert_called_once()
