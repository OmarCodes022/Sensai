"""Adapter failures keep safe, useful messages across the real process boundary."""

import json as json_module
from time import monotonic
from unittest.mock import MagicMock

import pytest

from sensai.chat.session import ChatSession
from sensai.core.cancellation import CancellationToken
from sensai.core.errors import LLMError
from sensai.core.isolation import ControlledLLMClient
from sensai.core.messages import Message
from sensai.llm import ollama
from sensai.llm.ollama_api import UsageError
from sensai.telemetry import BoundedEventSink


class LocalOllama(ollama.OllamaClient):
    """Patch HTTP inside the spawned child, while keeping the actual adapter."""

    def __init__(self):
        super().__init__()
        ollama.requests.post = self.post

    @staticmethod
    def post(url, *, json: dict, **kwargs):
        action = json["messages"][-1]["content"]
        resp = MagicMock(status_code=200)
        chunks = [{"message": {"role": "assistant", "content": "Complete"}, "done": True}]
        if action == "thinking":
            chunks = [
                {"message": {"role": "assistant", "content": "", "thinking": "private reasoning"}},
                {"done": True, "eval_count": 30},
            ]
        elif action == "http":
            resp.status_code = 503
        elif action == "invalid":
            chunks = [{"message": "private invalid payload"}]
        elif action == "remote":
            chunks = [{"error": "private remote details"}]
        elif action == "close":
            resp.close.side_effect = OSError("private close details")
        elif action == "unknown":
            raise RuntimeError("private unexpected details")
        resp.iter_lines.return_value = [json_module.dumps(chunk).encode() for chunk in chunks]
        return resp


def token():
    return CancellationToken(deadline=monotonic() + 10)


def test_thinking_only_worker_error_preserves_history_and_allows_next_turn():
    events, usages = [], []
    sink = BoundedEventSink(events.append)
    session = ChatSession(
        ControlledLLMClient(LocalOllama, event_sink=sink, usage_sink=usages.append),
        "model", "Shared",
    )
    assert list(session.send("success", token())) == ["Complete"]
    session.set_system_prompt("Current persona")
    previous = list(session.messages)

    with pytest.raises(LLMError, match="no visible answer") as error:
        list(session.send("thinking", token()))

    assert type(error.value) is LLMError
    assert session.messages == previous
    assert len(usages) == 2
    assert usages[-1].error == UsageError.INVALID_RESPONSE
    assert usages[-1].prompt_tokens is None
    assert usages[-1].output_tokens is None
    assert list(session.send("continue", token())) == ["Complete"]
    assert len(usages) == 3
    assert usages[-1].error is None
    assert [message.content for message in session.messages] == [
        "Current persona", "success", "Complete", "continue", "Complete",
    ]
    sink.drain()
    assert [event.name for event in events] == [
        "request.started", "request.completed", "request.started", "request.failed",
        "request.started", "request.completed",
    ]
    assert events[3].fields["error_code"] == "invalid_response"
    assert "private" not in str(error.value) + repr(events) + repr(usages)


@pytest.mark.parametrize("action, message, code", [
    ("http", "Ollama rejected the request", UsageError.HTTP),
    ("invalid", "invalid response from Ollama", UsageError.INVALID_RESPONSE),
    ("remote", "Ollama stream reported an error", UsageError.REMOTE),
    ("close", "failed to close Ollama response", UsageError.TRANSPORT),
    ("unknown", "Ollama stream failed", UsageError.TRANSPORT),
])
def test_adapter_failures_cross_worker_boundary_with_public_sanitized_error(action, message, code):
    usages = []
    client = ControlledLLMClient(LocalOllama, usage_sink=usages.append)
    with pytest.raises(LLMError, match=message) as error:
        list(client.stream("model", [Message(role="user", content=action)], token()))
    assert type(error.value) is LLMError
    assert "private" not in str(error.value)
    assert len(usages) == 1
    assert usages[0].error == code
