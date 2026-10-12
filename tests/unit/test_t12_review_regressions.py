"""PR review regressions, with local workers and deterministic teardown fakes."""
import errno
import signal
import termios
import time

import pytest

from sensai.app.session import ChatSession
from sensai.core.cancellation import CancellationToken, OperationCancelled, OperationTimedOut
from sensai.core.errors import ModelNotFoundError
from sensai.core import execution


class IteratorClient:
    def stream(self, model, messages, cancellation=None):
        return iter(["complete"])


@pytest.mark.parametrize("spawned", [False, True])
def test_iterator_without_close_can_finish_and_start_next_turn(spawned):
    client = execution.ControlledLLMClient(IteratorClient) if spawned else IteratorClient()
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

    monkeypatch.setattr(execution.os, "killpg", denied)
    monkeypatch.setattr(execution.os, "kill", lambda *args: pytest.fail("dead worker must not be signalled"))
    execution._stop(process)
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

    monkeypatch.setattr(execution.os, "killpg", denied)
    monkeypatch.setattr(execution.os, "kill", kill)
    execution._stop(process)
    assert signals == [signal.SIGTERM]
    assert process.joins and process.closed


def test_live_worker_signal_denial_is_not_hidden(monkeypatch):
    process = FakeProcess(alive=True)

    def denied(*args):
        raise PermissionError(errno.EPERM, "worker is inaccessible")

    monkeypatch.setattr(execution.os, "killpg", denied)
    monkeypatch.setattr(execution.os, "kill", denied)
    with pytest.raises(PermissionError):
        execution._stop(process)


def test_dead_group_permission_error_does_not_mask_known_child_error(monkeypatch):
    original = execution._stop

    def dead_stop(process):
        # The child finished reporting its known error; emulate macOS denying
        # the now-dead process group after the worker has been reaped.
        process.join(2)
        assert not process.is_alive()
        with monkeypatch.context() as patch:
            def denied(*args):
                raise PermissionError(errno.EPERM, "dead group")
            patch.setattr(execution.os, "killpg", denied)
            original(process)

    monkeypatch.setattr(execution, "_stop", dead_stop)
    with pytest.raises(ModelNotFoundError, match="missing model"):
        list(execution.ControlledLLMClient(MissingClient).stream("model", []))


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
    session = ChatSession(execution.ControlledLLMClient(CloseFailureClient), "model", "system")
    with pytest.raises(LLMError):
        list(session.send("abandoned"))
    assert len(session.messages) == 1


@pytest.mark.parametrize("spawned", [False, True])
def test_secondary_close_failure_preserves_primary_error_and_history(spawned):
    stream = FailingClient().stream("model", [])
    client = execution.ControlledLLMClient(FailingClient) if spawned else StreamClient(stream)
    session = ChatSession(client, "model", "system")
    with pytest.raises(ModelNotFoundError, match="original model error"):
        list(session.send("abandoned"))
    assert len(session.messages) == 1
    if not spawned:
        assert stream.close_count == 1
        assert list(session.send("next")) == ["next reply"]


def test_frames_preserve_primary_error_when_worker_stop_also_fails(monkeypatch):
    original = execution._stop

    def stop_then_fail(process):
        original(process)
        raise PermissionError("secondary teardown failure")

    monkeypatch.setattr(execution, "_stop", stop_then_fail)
    with pytest.raises(ModelNotFoundError, match="missing model"):
        list(execution.ControlledLLMClient(MissingClient).stream("model", []))


def test_terminal_comparison_masks_only_pendin(monkeypatch):
    from test_t12_terminal import stable_terminal_attrs
    pendin = 1 << 29
    attrs = [1, 2, 3, termios.ICANON | termios.ECHO | termios.ISIG, 4, 5, [b"x"]]
    monkeypatch.setattr(termios, "PENDIN", pendin, raising=False)
    monkeypatch.setattr(termios, "tcgetattr", lambda fd: [*attrs[:6], list(attrs[6])])
    before = stable_terminal_attrs(0)
    attrs[3] |= pendin
    assert stable_terminal_attrs(0) == before
    for flag in (termios.ICANON, termios.ECHO, termios.ISIG):
        attrs[3] ^= flag
        assert stable_terminal_attrs(0) != before
        attrs[3] ^= flag
    monkeypatch.delattr(termios, "PENDIN")
    assert stable_terminal_attrs(0) == attrs
