"""core.isolation: spawned-worker isolation, cancellation, deadlines and teardown.

Real spawned workers and local fakes only; no external service."""

import errno
from functools import partial
import multiprocessing
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

import pytest

from sensai.chat.session import ChatSession
from sensai.core import isolation
from sensai.core.cancellation import CancellationToken, OperationCancelled, OperationTimedOut
from sensai.core.ports import PolicyDenied, ToolCall, ToolResult
from sensai.core.errors import LLMError, ModelNotFoundError
from sensai.core.isolation import ControlledLLMClient, ControlledTool
from sensai.core.messages import Message
from sensai.llm.ollama_api import OllamaUsage, UsageError


class ChildClient:
    def __init__(self, marker=None):
        self._usage_sink = None
        if marker is not None:
            Path(marker).write_text("started")

    def stream(self, model, messages, cancellation=None):
        action = messages[-1].content
        if action == "success":
            yield "complete"
            if self._usage_sink:
                self._usage_sink(OllamaUsage(prompt_tokens=3, output_tokens=1, latency_ms=2))
            return
        if action == "crash":
            os._exit(7)
        if action == "missing":
            raise ModelNotFoundError("model unavailable")
        if action == "silent":
            time.sleep(30)
            return
        if action in ("descendant", "resistant"):
            if action == "resistant":
                signal.signal(signal.SIGTERM, signal.SIG_IGN)
                child = subprocess.Popen(
                    [sys.executable, "-c", "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); print('ready',flush=True); time.sleep(30)"],
                    stdout=subprocess.PIPE,
                )
                assert child.stdout.readline() == b"ready\n"
            else:
                child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
            yield f"{os.getpid()}:{child.pid}"
        else:
            yield str(os.getpid())
        if action == "continuous":
            while True:
                yield "x"
                time.sleep(0.01)
        time.sleep(30)


class ChildTool:
    def execute(self, call, cancellation=None):
        if call.name == "denied":
            raise PolicyDenied("action denied by policy")
        if call.name == "deadline":
            return ToolResult(str(cancellation.deadline))
        if call.name == "success":
            return ToolResult("complete")
        if call.name == "resistant":
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            threading.Thread(target=time.sleep, args=(30,), daemon=False).start()
            return ToolResult(str(os.getpid()))
        time.sleep(30)
        return ToolResult("too late")


def messages(action):
    return [Message(role="user", content=action)]


def assert_stopped(pid):
    """An unreaped orphan zombie is stopped too; no work can run in it."""
    limit = time.monotonic() + 1
    while time.monotonic() < limit:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        stat = Path(f"/proc/{pid}/stat")
        if stat.exists():
            try:
                if stat.read_text().split(") ", 1)[1].startswith("Z"):
                    return
            except (FileNotFoundError, ProcessLookupError):
                return
        time.sleep(0.01)
    pytest.fail(f"worker/descendant {pid} still running")


def test_pre_cancelled_request_never_starts_worker(tmp_path):
    marker = tmp_path / "started"
    token = CancellationToken()
    token.cancel()
    client = ControlledLLMClient(partial(ChildClient, str(marker)))
    with pytest.raises(OperationCancelled):
        list(client.stream("model", messages("success"), token))
    assert not marker.exists()


@pytest.mark.parametrize("action", ["block", "descendant", "resistant"])
def test_blocked_worker_and_descendants_stop_on_cancellation(action):
    client = ControlledLLMClient(ChildClient)
    token = CancellationToken(deadline=time.monotonic() + 5)
    stream = client.stream("model", messages(action), token)
    try:
        pids = [int(pid) for pid in next(stream).split(":")]
        started = time.monotonic()
        token.cancel()
        with pytest.raises(OperationCancelled):
            next(stream)
        assert time.monotonic() - started < 1
        for pid in pids:
            assert_stopped(pid)
        assert list(client.stream("model", messages("success"))) == ["complete"]
    finally:
        stream.close()


def test_cancellation_while_waiting_for_first_chunk():
    token = CancellationToken(deadline=time.monotonic() + 5)
    timer = threading.Timer(0.5, token.cancel)
    timer.start()
    started = time.monotonic()
    try:
        with pytest.raises(OperationCancelled):
            list(ControlledLLMClient(ChildClient).stream("model", messages("silent"), token))
        assert time.monotonic() - started < 1.5
    finally:
        timer.cancel()
        timer.join()


@pytest.mark.parametrize("action", ["silent", "continuous"])
def test_deadline_bounds_entire_operation_even_with_continuous_chunks(action):
    token = CancellationToken(deadline=time.monotonic() + 0.7)
    started = time.monotonic()
    with pytest.raises(OperationTimedOut):
        list(ControlledLLMClient(ChildClient).stream("model", messages(action), token))
    assert time.monotonic() - started < 1.5


@pytest.mark.parametrize("interrupt", ["close", "cancel", "timeout"])
def test_incomplete_turn_rolls_back_history_and_next_request_works(interrupt):
    client = ControlledLLMClient(ChildClient)
    session = ChatSession(client, "model", "system")
    assert list(session.send("success")) == ["complete"]
    previous = list(session.messages)
    token = CancellationToken(deadline=time.monotonic() + 5)
    stream = session.send("block", token)
    try:
        pid = int(next(stream))
        if interrupt == "close":
            stream.close()
        else:
            if interrupt == "cancel":
                token.cancel()
                error = OperationCancelled
            else:
                token.deadline = time.monotonic() - 1
                error = OperationTimedOut
            with pytest.raises(error):
                next(stream)
        assert session.messages == previous
        assert_stopped(pid)
        assert list(session.send("success")) == ["complete"]
    finally:
        stream.close()


def test_worker_crash_is_explicit_failure_and_known_error_preserved():
    client = ControlledLLMClient(ChildClient)
    with pytest.raises(LLMError):
        list(client.stream("model", messages("crash")))
    with pytest.raises(ModelNotFoundError, match="model unavailable"):
        list(client.stream("model", messages("missing")))
    assert list(client.stream("model", messages("success"))) == ["complete"]


@pytest.mark.parametrize("action, error", [("success", None), ("cancel", UsageError.CANCELLED), ("timeout", UsageError.TIMEOUT)])
def test_usage_and_terminal_event_are_once_only_and_callbacks_run_in_parent(action, error):
    received, usages, callback_pids = [], [], []

    class EventSink:
        def emit(self, event):
            callback_pids.append(os.getpid())
            received.append(event)

    def on_usage(usage):
        callback_pids.append(os.getpid())
        usages.append(usage)

    client = ControlledLLMClient(ChildClient, event_sink=EventSink(), usage_sink=on_usage)
    if action == "success":
        assert list(client.stream("model", messages("success"))) == ["complete"]
        assert usages[0].prompt_tokens == 3
        assert usages[0].output_tokens == 1
    else:
        token = CancellationToken(deadline=time.monotonic() + 5)
        stream = client.stream("model", messages("block"), token)
        try:
            next(stream)
            if action == "cancel":
                token.cancel()
                failure = OperationCancelled
            else:
                token.deadline = time.monotonic() - 1
                failure = OperationTimedOut
            with pytest.raises(failure):
                next(stream)
        finally:
            stream.close()
        assert usages[0].prompt_tokens is None
        assert usages[0].output_tokens is None
    assert len(usages) == 1
    assert usages[0].error == error
    assert len(received) == 2
    assert received[0].name == "request.started"
    assert received[1].name == ("request.completed" if error is None else "request.cancelled" if action == "cancel" else "request.failed")
    assert received[0].fields["operation_id"] == received[1].fields["operation_id"]
    assert set(callback_pids) == {os.getpid()}


def test_tool_receives_original_deadline_and_blocked_tool_is_interruptible():
    tool = ControlledTool(ChildTool)
    token = CancellationToken(deadline=time.monotonic() + 3)
    result = tool.execute(ToolCall("deadline", {}), token)
    assert float(result.output) == token.deadline
    token = CancellationToken(deadline=time.monotonic() + 0.7)
    started = time.monotonic()
    with pytest.raises(OperationTimedOut):
        tool.execute(ToolCall("block", {}), token)
    assert time.monotonic() - started < 1.5
    assert tool.execute(ToolCall("success", {})) == ToolResult("complete")
    assert not [child for child in multiprocessing.active_children() if child.is_alive()]


@pytest.mark.parametrize("interrupt", ["cancel", "timeout"])
def test_interrupt_after_final_chunk_is_not_committed_or_reported_as_success(interrupt):
    usages = []
    session = ChatSession(ControlledLLMClient(ChildClient, usage_sink=usages.append), "model", "sys")
    token = CancellationToken(deadline=time.monotonic() + 5)
    stream = session.send("success", token)
    try:
        assert next(stream) == "complete"
        if interrupt == "cancel":
            token.cancel()
            error, usage_error = OperationCancelled, UsageError.CANCELLED
        else:
            token.deadline = time.monotonic() - 1
            error, usage_error = OperationTimedOut, UsageError.TIMEOUT
        with pytest.raises(error):
            next(stream)
        assert [message.content for message in session.messages] == ["sys"]
        assert len(usages) == 1
        assert usages[0].error == usage_error
    finally:
        stream.close()


def test_session_passes_exact_original_token_and_deadline_to_backend():
    token = CancellationToken(deadline=time.monotonic() + 5)

    class RecordingClient:
        def stream(self, model, messages, cancellation=None):
            assert cancellation is token
            assert cancellation.deadline == token.deadline
            yield "reply"

    assert list(ChatSession(RecordingClient(), "model", "sys").send("hi", token)) == ["reply"]


def test_blocked_tool_cancellation_and_precancelled_tool():
    tool = ControlledTool(ChildTool)
    token = CancellationToken(deadline=time.monotonic() + 5)
    timer = threading.Timer(0.5, token.cancel)
    timer.start()
    started = time.monotonic()
    try:
        with pytest.raises(OperationCancelled):
            tool.execute(ToolCall("block", {}), token)
        assert time.monotonic() - started < 1.5
    finally:
        timer.cancel()
        timer.join()
    with pytest.raises(OperationCancelled):
        tool.execute(ToolCall("success", {}), token)
    assert not [child for child in multiprocessing.active_children() if child.is_alive()]


def test_tool_policy_denial_keeps_public_exception_type():
    with pytest.raises(PolicyDenied, match="action denied by policy"):
        ControlledTool(ChildTool).execute(ToolCall("denied", {}))


@pytest.mark.parametrize("interrupt", ["cancel", "timeout"])
def test_tool_rechecks_original_token_after_teardown(interrupt, monkeypatch):
    from sensai.core import isolation

    token = CancellationToken(deadline=time.monotonic() + 5)
    real_stop = isolation._stop

    def stop_then_interrupt(process):
        real_stop(process)
        if interrupt == "cancel":
            token.cancel()
        else:
            token.deadline = time.monotonic() - 1

    monkeypatch.setattr(isolation, "_stop", stop_then_interrupt)
    with pytest.raises(OperationCancelled if interrupt == "cancel" else OperationTimedOut):
        ControlledTool(ChildTool).execute(ToolCall("success", {}), token)


def test_tool_returning_with_sigterm_resistant_thread_is_force_stopped():
    started = time.monotonic()
    result = ControlledTool(ChildTool).execute(
        ToolCall("resistant", {}), CancellationToken(deadline=time.monotonic() + 5)
    )
    assert time.monotonic() - started < 1.5
    assert_stopped(int(result.output))


# --- Close, rollback and worker teardown edge cases ---

class IteratorClient:
    def stream(self, model, messages, cancellation=None):
        return iter(["complete"])


@pytest.mark.parametrize("spawned", [False, True])
def test_iterator_without_close_can_finish_and_start_next_turn(spawned):
    client = isolation.ControlledLLMClient(IteratorClient) if spawned else IteratorClient()
    session = ChatSession(client, "model", "system")
    assert list(session.send("first")) == ["complete"]
    assert list(session.send("second")) == ["complete"]
    assert [m.content for m in session.messages] == ["system", "first", "complete", "second", "complete"]


class ClosingStream:
    def __init__(self, callback):
        self.callback = callback
        self.close_count = 0
        self.chunks = iter(["complete"])

    def __iter__(self):
        return self

    def __next__(self):
        return next(self.chunks)

    def close(self):
        self.close_count += 1
        self.callback()


class StreamClient:
    def __init__(self, stream):
        self.current = stream

    def stream(self, model, messages, cancellation=None):
        stream, self.current = self.current, iter(["next reply"])
        return stream


@pytest.mark.parametrize("action, error", [("cancel", OperationCancelled), ("timeout", OperationTimedOut)])
def test_cancellation_during_close_rolls_back_before_commit(action, error):
    token = CancellationToken()

    def interrupt():
        if action == "cancel":
            token.cancel()
        else:
            token.deadline = time.monotonic() - 1

    stream = ClosingStream(interrupt)
    session = ChatSession(StreamClient(stream), "model", "system")
    before = list(session.messages)
    with pytest.raises(error):
        list(session.send("abandoned", token))
    assert session.messages == before
    assert stream.close_count == 1
    assert list(session.send("next")) == ["next reply"]


def test_failing_close_runs_once_and_rolls_back():
    def fail():
        raise RuntimeError("close failed")

    stream = ClosingStream(fail)
    session = ChatSession(StreamClient(stream), "model", "system")
    with pytest.raises(RuntimeError, match="close failed"):
        list(session.send("abandoned"))
    assert stream.close_count == 1
    assert len(session.messages) == 1
    assert list(session.send("next")) == ["next reply"]


class FakeProcess:
    pid = 12345

    def __init__(self, alive=False):
        self.alive = alive
        self.joins = []
        self.closed = False

    def is_alive(self):
        return self.alive

    def join(self, timeout=None):
        self.joins.append(timeout)

    def close(self):
        assert not self.alive
        self.closed = True


def test_dead_worker_group_permission_error_is_benign_and_reaped(monkeypatch):
    process = FakeProcess()

    def denied(*args):
        raise PermissionError(errno.EPERM, "group is inaccessible")

    monkeypatch.setattr(isolation.os, "killpg", denied)
    monkeypatch.setattr(isolation.os, "kill", lambda *args: pytest.fail("dead worker must not be signalled"))
    isolation._stop(process)
    assert process.joins and process.closed


def test_live_worker_group_permission_error_falls_back_to_pid(monkeypatch):
    process = FakeProcess(alive=True)
    signals = []

    def denied(*args):
        raise PermissionError(errno.EPERM, "group is inaccessible")

    def kill(pid, sig):
        assert pid == process.pid
        signals.append(sig)
        process.alive = False

    monkeypatch.setattr(isolation.os, "killpg", denied)
    monkeypatch.setattr(isolation.os, "kill", kill)
    isolation._stop(process)
    assert signals == [signal.SIGTERM]
    assert process.joins and process.closed


def test_live_worker_signal_denial_is_not_hidden(monkeypatch):
    process = FakeProcess(alive=True)

    def denied(*args):
        raise PermissionError(errno.EPERM, "worker is inaccessible")

    monkeypatch.setattr(isolation.os, "killpg", denied)
    monkeypatch.setattr(isolation.os, "kill", denied)
    with pytest.raises(PermissionError):
        isolation._stop(process)


def test_dead_group_permission_error_does_not_mask_known_child_error(monkeypatch):
    original = isolation._stop

    def dead_stop(process):
        # The child finished reporting its known error; emulate macOS denying
        # the now-dead process group after the worker has been reaped.
        process.join(2)
        assert not process.is_alive()
        with monkeypatch.context() as patch:
            def denied(*args):
                raise PermissionError(errno.EPERM, "dead group")
            patch.setattr(isolation.os, "killpg", denied)
            original(process)

    monkeypatch.setattr(isolation, "_stop", dead_stop)
    with pytest.raises(ModelNotFoundError, match="missing model"):
        list(isolation.ControlledLLMClient(MissingClient).stream("model", []))


class MissingClient:
    def stream(self, model, messages, cancellation=None):
        raise ModelNotFoundError("missing model")


class FailingStream(ClosingStream):
    def __next__(self):
        raise ModelNotFoundError("original model error")


class FailingClient:
    def stream(self, model, messages, cancellation=None):
        def fail_close():
            raise RuntimeError("secondary close failure")
        return FailingStream(fail_close)


class CloseFailureClient:
    def stream(self, model, messages, cancellation=None):
        def fail_close():
            raise RuntimeError("close failed")
        return ClosingStream(fail_close)


def test_close_failure_is_not_hidden_by_unrelated_handled_exception():
    session = ChatSession(CloseFailureClient(), "model", "system")
    try:
        raise ValueError("unrelated handled caller error")
    except ValueError:
        with pytest.raises(RuntimeError, match="close failed"):
            list(session.send("abandoned"))
    assert len(session.messages) == 1


def test_spawned_stream_close_failure_after_success_is_explicit():
    from sensai.core.errors import LLMError
    session = ChatSession(isolation.ControlledLLMClient(CloseFailureClient), "model", "system")
    with pytest.raises(LLMError):
        list(session.send("abandoned"))
    assert len(session.messages) == 1


@pytest.mark.parametrize("spawned", [False, True])
def test_secondary_close_failure_preserves_primary_error_and_history(spawned):
    stream = FailingClient().stream("model", [])
    client = isolation.ControlledLLMClient(FailingClient) if spawned else StreamClient(stream)
    session = ChatSession(client, "model", "system")
    with pytest.raises(ModelNotFoundError, match="original model error"):
        list(session.send("abandoned"))
    assert len(session.messages) == 1
    if not spawned:
        assert stream.close_count == 1
        assert list(session.send("next")) == ["next reply"]


def test_frames_preserve_primary_error_when_worker_stop_also_fails(monkeypatch):
    original = isolation._stop

    def stop_then_fail(process):
        original(process)
        raise PermissionError("secondary teardown failure")

    monkeypatch.setattr(isolation, "_stop", stop_then_fail)
    with pytest.raises(ModelNotFoundError, match="missing model"):
        list(isolation.ControlledLLMClient(MissingClient).stream("model", []))
