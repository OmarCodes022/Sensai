import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from sensai.core.contracts import Event, EventPort
from sensai.core.errors import LLMError
from sensai.llm.ollama import OllamaClient
from sensai.llm.schemas import OllamaUsage, UsageError
from sensai.core.messages import Message
from sensai.observability.telemetry import (
    BoundedEventSink,
    EventDeliveryError,
    EventName,
    Telemetry,
    new_operation_id,
)


def response(*chunks):
    resp = MagicMock(status_code=200)
    resp.iter_lines.return_value = [json.dumps(chunk).encode() for chunk in chunks]
    return resp


def test_final_chunk_reports_typed_usage_and_private_safe_events():
    received = []
    usages = []
    sink = BoundedEventSink(received.append)
    assert isinstance(sink, EventPort)
    resp = response(
        {"message": {"role": "assistant", "content": "secret reply"}, "done": False},
        {
            "message": {"role": "assistant", "content": "!"},
            "done": True,
            "prompt_eval_count": 7,
            "eval_count": 2,
            "total_duration": 30_000_000,
        },
    )
    with patch("sensai.llm.ollama.requests.post", return_value=resp) as post:
        with patch("sensai.llm.ollama.perf_counter", side_effect=[1, 1.02]):
            assert list(
                OllamaClient(event_sink=sink, usage_sink=usages.append).stream(
                    "m", [Message(role="user", content="private prompt")]
                )
            ) == ["secret reply", "!"]
    assert post.call_args.kwargs["json"] == {
        "model": "m",
        "messages": [{"role": "user", "content": "private prompt"}],
        "stream": True,
    }
    assert len(usages) == 1
    assert isinstance(usages[0], OllamaUsage)
    assert usages[0].prompt_tokens == 7
    assert usages[0].output_tokens == 2
    assert usages[0].latency_ms == pytest.approx(20)
    assert usages[0].server_duration_ms == 30
    assert usages[0].error is None
    assert sink.pending == 2
    assert sink.drain() == 2
    assert [event.name for event in received] == [
        EventName.REQUEST_STARTED.value,
        EventName.REQUEST_COMPLETED.value,
    ]
    assert received[0].fields["operation_id"] == received[1].fields["operation_id"]
    assert received[1].fields["prompt_tokens"] == "7"
    assert received[1].fields["output_tokens"] == "2"
    assert received[1].fields["server_duration_ms"] == "30.0"
    assert float(received[1].fields["latency_ms"]) == pytest.approx(20)
    assert "private" not in repr(received)
    assert "secret" not in repr(received)
    resp.close.assert_called_once()


def test_missing_token_counts_remain_absent_and_stream_ends_only_at_done():
    usages = []
    received = []
    sink = BoundedEventSink(received.append)
    resp = response({"message": {"role": "assistant", "content": "answer"}},
                    {"done": True})
    with patch("sensai.llm.ollama.requests.post", return_value=resp):
        assert list(OllamaClient(event_sink=sink, usage_sink=usages.append).stream(
            "m", [Message(role="user", content="prompt")]
        )) == ["answer"]
    sink.drain()
    assert usages[0].prompt_tokens is None
    assert usages[0].output_tokens is None
    assert usages[0].error is None
    assert set(received[1].fields) == {"operation_id", "latency_ms"}
    resp.close.assert_called_once()


def test_incomplete_stream_reports_error_without_inventing_counts():
    received, usages = [], []
    sink = BoundedEventSink(received.append)
    resp = response({"message": {"role": "assistant", "content": "partial"}})
    with patch("sensai.llm.ollama.requests.post", return_value=resp):
        stream = OllamaClient(event_sink=sink, usage_sink=usages.append).stream(
            "m", [Message(role="user", content="private")]
        )
        assert next(stream) == "partial"
        with pytest.raises(LLMError, match="incomplete response"):
            next(stream)
    sink.drain()
    assert usages[0].error == UsageError.INCOMPLETE_STREAM
    assert usages[0].prompt_tokens is None
    assert received[1].fields["error_code"] == "incomplete_stream"
    assert "partial" not in repr(received)
    resp.close.assert_called_once()


def test_early_close_reports_cancelled_and_closes_http_response():
    usages = []
    resp = response({"message": {"role": "assistant", "content": "first"}},
                    {"done": True, "eval_count": 100})
    with patch("sensai.llm.ollama.requests.post", return_value=resp):
        stream = OllamaClient(usage_sink=usages.append).stream(
            "m", [Message(role="user", content="hello")]
        )
        assert next(stream) == "first"
        stream.close()
    assert usages[0].error == UsageError.CANCELLED
    assert usages[0].output_tokens is None
    resp.close.assert_called_once()


def test_close_after_done_chunk_content_reports_cancelled_not_success():
    received, usages = [], []
    sink = BoundedEventSink(received.append)
    resp = response(
        {"done": True, "message": {"role": "assistant", "content": "last"},
         "prompt_eval_count": 3, "eval_count": 1}
    )
    with patch("sensai.llm.ollama.requests.post", return_value=resp):
        stream = OllamaClient(event_sink=sink, usage_sink=usages.append).stream(
            "m", [Message(role="user", content="private")]
        )
        assert next(stream) == "last"
        assert usages == []
        stream.close()
    assert len(usages) == 1
    assert usages[0].error == UsageError.CANCELLED
    assert usages[0].prompt_tokens is None
    assert usages[0].output_tokens is None
    assert sink.drain() == 2
    assert [event.name for event in received] == [
        EventName.REQUEST_STARTED.value,
        EventName.REQUEST_CANCELLED.value,
    ]
    resp.close.assert_called_once()


def test_close_failure_during_cancellation_is_sanitized_and_reported():
    received, usages = [], []
    sink = BoundedEventSink(received.append)
    resp = response({"message": {"role": "assistant", "content": "part"}})
    resp.close.side_effect = OSError("private close detail")
    with patch("sensai.llm.ollama.requests.post", return_value=resp):
        stream = OllamaClient(event_sink=sink, usage_sink=usages.append).stream("m", [])
        assert next(stream) == "part"
        with pytest.raises(LLMError, match="failed to close Ollama response") as error:
            stream.close()
    assert "private" not in str(error.value)
    assert len(usages) == 1
    assert usages[0].error == UsageError.TRANSPORT
    assert sink.drain() == 2
    assert received[1].name == EventName.REQUEST_FAILED.value
    resp.close.assert_called_once()


@pytest.mark.parametrize(
    ("exception", "code"),
    [
        (requests.ConnectionError("private prompt"), UsageError.CONNECTION),
        (requests.Timeout("private prompt"), UsageError.TIMEOUT),
        (requests.RequestException("private prompt"), UsageError.TRANSPORT),
    ],
)
def test_transport_failures_are_sanitized_and_typed(exception, code):
    usages = []
    with patch("sensai.llm.ollama.requests.post", side_effect=exception):
        with pytest.raises(LLMError) as error:
            list(OllamaClient(usage_sink=usages.append).stream("m", []))
    assert "private prompt" not in str(error.value)
    assert usages[0].error == code


def test_remote_error_is_sanitized_and_closes_response():
    usages = []
    resp = response({"error": "private response or secret tool arguments"})
    with patch("sensai.llm.ollama.requests.post", return_value=resp):
        with pytest.raises(LLMError) as error:
            list(OllamaClient(usage_sink=usages.append).stream("m", []))
    assert "private" not in str(error.value)
    assert usages[0].error == UsageError.REMOTE
    resp.close.assert_called_once()


def test_invalid_final_usage_is_not_reported_as_success():
    usages = []
    resp = response({"done": True, "eval_count": "private response"})
    with patch("sensai.llm.ollama.requests.post", return_value=resp):
        with pytest.raises(LLMError, match="invalid response"):
            list(OllamaClient(usage_sink=usages.append).stream("m", []))
    assert usages[0].error == UsageError.INVALID_RESPONSE
    assert usages[0].output_tokens is None
    resp.close.assert_called_once()


def test_iteration_failure_sanitizes_exception_and_closes_response():
    usages = []
    resp = MagicMock(status_code=200)
    resp.iter_lines.side_effect = requests.RequestException("private streamed data")
    with patch("sensai.llm.ollama.requests.post", return_value=resp):
        with pytest.raises(LLMError) as error:
            list(OllamaClient(usage_sink=usages.append).stream("m", []))
    assert "private" not in str(error.value)
    assert usages[0].error == UsageError.TRANSPORT
    resp.close.assert_called_once()


def test_close_failure_after_final_frame_reports_failure_not_success():
    received, usages = [], []
    sink = BoundedEventSink(received.append)
    resp = response(
        {"done": True, "message": {"role": "assistant", "content": "reply"},
         "prompt_eval_count": 2, "eval_count": 1}
    )
    resp.close.side_effect = OSError("private close detail")
    with patch("sensai.llm.ollama.requests.post", return_value=resp):
        with pytest.raises(LLMError, match="failed to close Ollama response") as error:
            assert list(
                OllamaClient(event_sink=sink, usage_sink=usages.append).stream("m", [])
            ) == ["reply"]
    assert "private" not in str(error.value)
    assert len(usages) == 1
    assert usages[0].error == UsageError.TRANSPORT
    assert usages[0].prompt_tokens is None
    assert usages[0].output_tokens is None
    assert sink.drain() == 2
    assert [event.name for event in received] == [
        EventName.REQUEST_STARTED.value,
        EventName.REQUEST_FAILED.value,
    ]
    assert received[1].fields["error_code"] == "transport"
    resp.close.assert_called_once()


def test_close_failure_does_not_mask_primary_llm_error():
    received, usages = [], []
    sink = BoundedEventSink(received.append)
    resp = response({"error": "private remote detail"})
    resp.close.side_effect = OSError("private close detail")
    with patch("sensai.llm.ollama.requests.post", return_value=resp):
        with pytest.raises(LLMError, match="Ollama stream reported an error") as error:
            list(OllamaClient(event_sink=sink, usage_sink=usages.append).stream("m", []))
    assert "private" not in str(error.value)
    if hasattr(error.value, "add_note"):
        assert error.value.__notes__ == ["Ollama response close failed"]
    assert len(usages) == 1
    assert usages[0].error == UsageError.REMOTE
    assert sink.drain() == 2
    assert received[1].fields["error_code"] == "remote"
    resp.close.assert_called_once()


def test_http_response_is_closed_on_model_not_found():
    usages = []
    resp = MagicMock(status_code=404)
    with patch("sensai.llm.ollama.requests.post", return_value=resp):
        with pytest.raises(LLMError, match="ollama pull m"):
            list(OllamaClient(usage_sink=usages.append).stream("m", []))
    assert usages[0].error == UsageError.MODEL_NOT_FOUND
    resp.close.assert_called_once()


def test_bounded_delivery_snapshots_fields_and_rejects_private_metadata():
    received = []
    sink = BoundedEventSink(received.append, max_events=1)
    operation_id = new_operation_id()
    fields = {"operation_id": operation_id}
    sink.emit(Event("tool.started", fields))
    fields["operation_id"] = new_operation_id()
    with pytest.raises(EventDeliveryError, match="queue is full"):
        sink.emit(Event("tool.started", {"operation_id": new_operation_id()}))
    assert sink.drain(limit=1) == 1
    assert received[0].fields["operation_id"] == operation_id
    with pytest.raises(TypeError):
        received[0].fields["prompt"] = "secret"
    for event in (
        Event("tool.started", {"operation_id": operation_id, "arguments": "secret"}),
        Event(
            "request.completed", {"operation_id": operation_id, "latency_ms": "secret"}
        ),
        Event(
            "request.completed",
            {"operation_id": operation_id, "latency_ms": "1", "prompt_tokens": "1.5"},
        ),
        Event("custom", {"operation_id": operation_id}),
        Event("tool.started", {"operation_id": "private prompt"}),
    ):
        with pytest.raises(
            ValueError, match="invalid or disallowed telemetry event"
        ) as error:
            sink.emit(event)
        assert "secret" not in str(error.value)
        assert "private" not in str(error.value)
    assert sink.pending == 0


def test_event_backpressure_propagates_and_response_still_closes():
    sink = BoundedEventSink(lambda _: None, max_events=1)
    resp = response({"done": True})
    with patch("sensai.llm.ollama.requests.post", return_value=resp):
        with pytest.raises(EventDeliveryError, match="queue is full"):
            list(OllamaClient(event_sink=sink).stream("m", []))
    assert sink.pending == 1
    resp.close.assert_called_once()


def test_subscriber_failure_is_explicit_and_keeps_event_for_retry():
    seen = []

    def subscriber(event):
        seen.append(event.name)
        if len(seen) == 1:
            raise RuntimeError("private subscriber details")

    sink = BoundedEventSink(subscriber)
    sink.emit(Event("request.started", {"operation_id": new_operation_id()}))
    with pytest.raises(EventDeliveryError, match="subscriber failed") as error:
        sink.drain()
    assert "private" not in str(error.value)
    assert sink.pending == 1
    assert sink.drain() == 1
    assert seen == ["request.started", "request.started"]


def test_tool_lifecycle_has_no_arguments_or_results_and_is_instance_isolated():
    received = []
    sink = BoundedEventSink(received.append)
    other = BoundedEventSink(lambda _: None)
    telemetry = Telemetry(sink)
    tool_id = new_operation_id()
    telemetry.tool_started(tool_id)
    telemetry.tool_finished(tool_id, 4.0)
    telemetry.tool_started(tool_id)
    telemetry.tool_finished(tool_id, 7.5, UsageError.TOOL_FAILURE)
    assert sink.pending == 4
    assert other.pending == 0
    assert sink.drain() == 4
    assert [event.name for event in received] == [
        "tool.started", "tool.completed", "tool.started", "tool.failed"
    ]
    assert received[-1].fields["error_code"] == "tool_failure"
