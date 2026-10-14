"""Context limits must be explicit and truncation must not commit a turn."""

import json as json_module
from time import monotonic
from unittest.mock import MagicMock, patch

import pytest

from sensai.app.session import ChatSession
from sensai.app.settings import Settings
from sensai.core.cancellation import CancellationToken
from sensai.core.errors import LLMError
from sensai.core.messages import Message
from sensai.llm import create_client, ollama
from sensai.llm.ollama import OllamaClient
from sensai.llm.schemas import UsageError
from sensai.observability.telemetry import BoundedEventSink


def response(*chunks):
    resp = MagicMock(status_code=200)
    resp.iter_lines.return_value = [json_module.dumps(chunk).encode() for chunk in chunks]
    return resp


@pytest.mark.parametrize("source", ["direct", "factory"])
@pytest.mark.parametrize("context", [None, 8192])
def test_context_setting_reaches_request_without_overriding_thinking(monkeypatch, source, context):
    monkeypatch.delenv("SENSAI_CONTEXT_LENGTH", raising=False)
    if context is not None:
        monkeypatch.setenv("SENSAI_CONTEXT_LENGTH", str(context))
    client = create_client(Settings(_env_file=None)) if source == "factory" else OllamaClient(context_length=context)
    resp = response({"message": {"role": "assistant", "content": "Answer"}, "done": True})
    with patch("sensai.llm.ollama.requests.post", return_value=resp) as post:
        assert list(client.stream("model", [Message(role="user", content="Question")])) == ["Answer"]
    expected = {
        "model": "model", "messages": [{"role": "user", "content": "Question"}], "stream": True,
    }
    if context is not None:
        expected["options"] = {"num_ctx": context}
    assert post.call_args.kwargs["json"] == expected
    resp.close.assert_called_once()


@pytest.mark.parametrize("context", [0, -1, True, False, 8192.5, "8192", "bad"])
def test_direct_client_rejects_invalid_context_length(context):
    with pytest.raises(ValueError, match="positive integer"):
        OllamaClient(context_length=context)


@pytest.mark.parametrize("partial", ["", "Partial answer"])
def test_length_completion_rolls_back_even_with_visible_output(partial):
    usages, events = [], []
    sink = BoundedEventSink(events.append)
    client = OllamaClient(event_sink=sink, usage_sink=usages.append)
    session = ChatSession(client, "model", "Shared")
    earlier = response({"message": {"role": "assistant", "content": "Earlier answer"}, "done": True})
    truncated = response(
        {"message": {"role": "assistant", "content": partial, "thinking": "private reasoning"}},
        {"done": True, "done_reason": "length", "prompt_eval_count": 2987, "eval_count": 1109},
    )
    following = response({"message": {"role": "assistant", "content": "Next answer"}, "done": True})
    with patch("sensai.llm.ollama.requests.post", side_effect=[earlier, truncated, following]) as post:
        list(session.send("Earlier question"))
        session.set_system_prompt("Current persona")
        previous = list(session.messages)
        stream = session.send("Failed question")
        if partial:
            assert next(stream) == partial
        with pytest.raises(LLMError, match="token limit reached") as error:
            next(stream)
        assert type(error.value) is LLMError
        assert session.messages == previous
        assert len(usages) == 2
        assert usages[-1].error == UsageError.INCOMPLETE_STREAM
        assert usages[-1].prompt_tokens is None
        assert usages[-1].output_tokens is None
        assert list(session.send("Next question")) == ["Next answer"]
        assert [message["content"] for message in post.call_args.kwargs["json"]["messages"]] == [
            "Current persona", "Earlier question", "Earlier answer", "Current persona", "Next question",
        ]
    truncated.close.assert_called_once()
    assert len(usages) == 3
    sink.drain()
    assert [event.name for event in events] == [
        "request.started", "request.completed", "request.started", "request.failed",
        "request.started", "request.completed",
    ]
    assert events[3].fields["error_code"] == "incomplete_stream"
    assert "private" not in str(error.value) + repr(events) + repr(usages)


class ContextLocalOllama(OllamaClient):
    """Fake HTTP inside the real controlled-client factory's child."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        ollama.requests.post = self.post

    @staticmethod
    def post(url, *, json, **kwargs):
        assert json.get("options") == {"num_ctx": 8192}
        assert "think" not in json
        if json["messages"][-1]["content"] == "truncated":
            return response({"done": True, "done_reason": "length", "eval_count": 4096})
        return response({"message": {"role": "assistant", "content": "Answer"}, "done": True})


def test_controlled_factory_keeps_configured_context_and_public_length_error(monkeypatch):
    usages = []
    monkeypatch.setattr(ollama, "OllamaClient", ContextLocalOllama)
    client = OllamaClient(context_length=8192, usage_sink=usages.append)
    with pytest.raises(LLMError, match="token limit reached") as error:
        list(client.stream("model", [Message(role="user", content="truncated")],
                           CancellationToken(deadline=monotonic() + 10)))
    assert type(error.value) is LLMError
    assert len(usages) == 1
    assert usages[0].error == UsageError.INCOMPLETE_STREAM
    assert list(client.stream("model", [Message(role="user", content="next")],
                              CancellationToken(deadline=monotonic() + 10))) == ["Answer"]
    assert len(usages) == 2
    assert usages[1].error is None
