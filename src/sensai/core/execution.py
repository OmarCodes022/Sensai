"""Interruptible POSIX execution. Factories must be importable and pickleable."""
from collections.abc import Callable, Iterator, Sequence
from dataclasses import asdict
import json
import multiprocessing
import os
import select
import signal
import socket
from time import monotonic

from sensai.core.cancellation import CancellationToken, OperationCancelled, OperationTimedOut
from sensai.core.contracts import PolicyDenied, PortError, ToolCall, ToolResult
from sensai.core.errors import LLMConnectionError, LLMError, ModelNotFoundError, SensaiError
from sensai.core.messages import Message
from sensai.llm.base import LLMClient, close_stream
from sensai.llm.schemas import OllamaUsage, UsageError


_ERRORS = {cls.__name__: cls for cls in (
    LLMError, LLMConnectionError, ModelNotFoundError, PortError, PolicyDenied,
    OperationCancelled, OperationTimedOut, ValueError,
)}


def _child(channel, factory, kind, arguments, deadline):
    """All external work and any descendants belong to this process group."""
    os.setsid()

    def emit(name, value=None):
        channel.sendall((json.dumps([name, value], ensure_ascii=False) + "\n").encode())

    try:
        emit("ready")
        worker = factory()
        token = CancellationToken(deadline)
        if kind == "stream":
            if hasattr(worker, "_usage_sink"):
                worker._usage_sink = lambda usage: emit("usage", asdict(usage))
            # This worker is already isolated: don't recursively wrap Ollama.
            from sensai.llm.ollama import OllamaClient
            if isinstance(worker, OllamaClient):
                stream = worker._stream_direct(*arguments)
            else:
                stream = worker.stream(*arguments, cancellation=token)
            failure = None
            try:
                for chunk in stream:
                    token.raise_if_cancelled()
                    emit("chunk", chunk)
                token.raise_if_cancelled()
            except BaseException as exc:
                failure = exc
                raise
            finally:
                close_stream(stream, failure)
        else:
            token.raise_if_cancelled()
            result = worker.execute(arguments[0], cancellation=token)
            token.raise_if_cancelled()
            emit("result", result.output)
        emit("done")
    except BaseException as exc:
        name = type(exc).__name__
        message = str(exc) if name in _ERRORS else "execution worker failed"
        if name not in _ERRORS:
            # Preserve the public hierarchy, never deserialize arbitrary classes.
            name = "LLMError" if kind == "stream" else "PortError"
        try:
            emit("error", [name, message])
        except (OSError, ValueError):
            pass
    finally:
        channel.close()


def _stop(process):
    if process.pid is None:
        return
    def kill_group(sig):
        try:
            os.killpg(process.pid, sig)
        except (ProcessLookupError, PermissionError):
            # macOS can deny signalling an exited group; reap before deciding.
            if process.is_alive():
                try:
                    os.kill(process.pid, sig)
                except ProcessLookupError:
                    pass  # The child exited between the liveness check and signal.
    try:
        kill_group(signal.SIGTERM)
    finally:
        try:
            process.join(.2)
            # Also kill descendants whose parent already exited normally.
            kill_group(signal.SIGKILL)
            process.join()
        finally:
            if not process.is_alive():
                process.join()
                process.close()


def _frames(factory, kind, arguments, cancellation):
    token = cancellation or CancellationToken()
    token.raise_if_cancelled()
    parent, child = socket.socketpair()
    process = multiprocessing.get_context("spawn").Process(
        target=_child, args=(child, factory, kind, arguments, token.deadline),
    )
    parent.setblocking(False)
    failure = None
    try:
        process.start()
        child.close()
        buffer = b""
        while True:
            token.raise_if_cancelled()
            delay = .02
            if token.deadline is not None:
                delay = min(delay, max(0, token.deadline - monotonic()))
            if not select.select([parent], [], [], delay)[0]:
                if not process.is_alive():
                    raise (LLMError if kind == "stream" else PortError)(
                        "execution process exited without completing")
                continue
            data = parent.recv(65536)
            if not data:
                raise (LLMError if kind == "stream" else PortError)(
                    "execution channel closed without completing")
            buffer += data
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                token.raise_if_cancelled()
                name, value = json.loads(line)
                if name == "done":
                    return
                if name == "error":
                    cls, message = value
                    raise _ERRORS[cls](message)
                yield name, value
    except BaseException as exc:
        failure = exc
        raise
    finally:
        child.close()
        parent.close()
        try:
            _stop(process)
        except OSError as exc:
            cleanup_error = (LLMError if kind == "stream" else PortError)(
                "execution worker cleanup failed")
            if failure is None or isinstance(failure, GeneratorExit):
                raise cleanup_error from exc
            if hasattr(failure, "add_note"):
                failure.add_note(str(cleanup_error))


class ControlledLLMClient(LLMClient):
    """Run a client constructed by factory in a fresh process for each turn."""
    def __init__(self, factory: Callable[[], LLMClient], event_sink=None, usage_sink=None):
        self.factory = factory
        self.usage_sink = usage_sink
        self.telemetry = None
        if event_sink is not None:
            from sensai.observability.telemetry import Telemetry
            self.telemetry = Telemetry(event_sink)

    def stream(self, model: str, messages: Sequence[Message],
               cancellation: CancellationToken | None = None) -> Iterator[str]:
        if cancellation is not None:
            cancellation.raise_if_cancelled()
        from sensai.observability.telemetry import new_operation_id
        operation_id = new_operation_id()
        started = monotonic()
        usage = None
        outcome = UsageError.TRANSPORT
        frames = _frames(self.factory, "stream", (model, list(messages)), cancellation)
        try:
            if self.telemetry is not None:
                self.telemetry.request_started(operation_id)
            for name, value in frames:
                if name == "chunk":
                    yield value
                elif name == "usage":
                    usage = OllamaUsage(**{**value, "error": UsageError(value["error"]) if value["error"] else None})
            if cancellation is not None:
                cancellation.raise_if_cancelled()
            outcome = None
        except (OperationCancelled, GeneratorExit, KeyboardInterrupt):
            outcome = UsageError.CANCELLED
            raise
        except OperationTimedOut:
            outcome = UsageError.TIMEOUT
            raise
        except SensaiError:
            outcome = usage.error if usage is not None else UsageError.TRANSPORT
            raise
        finally:
            frames.close()
            final = OllamaUsage(
                prompt_tokens=usage.prompt_tokens if usage and outcome is None else None,
                output_tokens=usage.output_tokens if usage and outcome is None else None,
                latency_ms=(monotonic() - started) * 1000,
                error=outcome,
                server_duration_ms=usage.server_duration_ms if usage and outcome is None else None,
            )
            try:
                if self.usage_sink is not None:
                    self.usage_sink(final)
            finally:
                if self.telemetry is not None:
                    self.telemetry.request_finished(operation_id, final)


class ControlledTool:
    """Construct a tool in the child, never pass an open DB/resource connection."""
    def __init__(self, factory):
        self.factory = factory

    def execute(self, call: ToolCall, cancellation: CancellationToken | None = None) -> ToolResult:
        result = None
        frames = _frames(self.factory, "tool", (call,), cancellation)
        try:
            for name, value in frames:
                if name == "result":
                    result = ToolResult(value)
        finally:
            frames.close()
        if cancellation is not None:
            cancellation.raise_if_cancelled()
        if result is None:
            raise PortError("tool completed without a result")
        return result
