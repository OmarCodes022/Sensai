"""Real POSIX terminal checks, without an Ollama server."""

from contextlib import contextmanager
import io
import os
import pty
import termios
import threading
import time

import pytest

from sensai.app.terminal import TerminalInput
from sensai.app.cli import parse_args, repl
from sensai.app.session import ChatSession
from sensai.app.settings import Settings
from sensai.core.cancellation import OperationCancelled, OperationTimedOut
from fakes import FakeClient


def stable_terminal_attrs(fd):
    attrs = termios.tcgetattr(fd)
    # macOS may set this transient input-reprint flag after restoration.
    attrs[3] &= ~getattr(termios, "PENDIN", 0)
    return attrs


@contextmanager
def terminal():
    master, slave = pty.openpty()
    before = stable_terminal_attrs(slave)
    stdin = os.fdopen(os.dup(slave), "r", encoding="utf-8")
    stdout = os.fdopen(os.dup(slave), "w", encoding="utf-8")
    watchdog = threading.Timer(2, os.write, (master, b"\x04"))
    try:
        with TerminalInput(stdin=stdin, stdout=stdout) as reader:
            watchdog.start()
            yield reader, master
        assert stable_terminal_attrs(slave) == before
    finally:
        watchdog.cancel()
        if watchdog.ident is not None:
            watchdog.join()
        stdin.close()
        stdout.close()
        os.close(master)
        os.close(slave)


def feed(master, content):
    timer = threading.Timer(0.03, os.write, (master, content))
    timer.start()
    return timer


@pytest.mark.parametrize("key", [b"\x03", b"\x1b"])
def test_cancel_key_interrupts_pending_input_then_next_prompt_works(key):
    with terminal() as (reader, master):
        timer = feed(master, b"abandoned" + key)
        try:
            with pytest.raises(KeyboardInterrupt):
                reader.read("> ")
        finally:
            timer.join()
        timer = feed(master, b"fresh\r")
        try:
            assert reader.read("> ") == "fresh"
        finally:
            timer.join()


def test_unicode_paste_backspace_and_arrow_sequence_do_not_cancel_input():
    with terminal() as (reader, master):
        timer = feed(master, "caféX\x7f\x1b[A collé\r".encode())
        try:
            assert reader.read("> ") == "café collé"
        finally:
            timer.join()


@pytest.mark.parametrize("key", [b"\x03", b"\x1b"])
def test_streaming_poll_recognizes_cancel_without_newline(key):
    with terminal() as (reader, master):
        assert not reader.cancel_requested()
        os.write(master, key)
        limit = time.monotonic() + 0.5
        while time.monotonic() < limit:
            if reader.cancel_requested():
                break
            time.sleep(0.01)
        else:
            pytest.fail("cancel key was not observed during streaming")


def test_arrow_sequence_does_not_cancel_streaming():
    with terminal() as (reader, master):
        os.write(master, b"\x1b[A\x1b[B\x1b[C\x1b[D")
        for _ in range(10):
            assert not reader.cancel_requested()
            time.sleep(0.01)


def test_terminal_restored_after_error():
    master, slave = pty.openpty()
    before = stable_terminal_attrs(slave)
    stdin = os.fdopen(os.dup(slave), "r")
    try:
        with pytest.raises(RuntimeError, match="boom"):
            with TerminalInput(stdin=stdin, stdout=io.StringIO()):
                raise RuntimeError("boom")
        assert stable_terminal_attrs(slave) == before
    finally:
        stdin.close()
        os.close(master)
        os.close(slave)


def test_empty_ctrl_d_exits_and_non_tty_keeps_line_input():
    with terminal() as (reader, master):
        timer = feed(master, b"\x04")
        try:
            with pytest.raises(EOFError):
                reader.read("> ")
        finally:
            timer.join()
    with TerminalInput(stdin=io.StringIO("one\ntwo\n"), stdout=io.StringIO()) as reader:
        assert reader.read("> ") == "one"
        assert reader.read("> ") == "two"
        assert not reader.cancel_requested()
        with pytest.raises(EOFError):
            reader.read("> ")


@pytest.mark.parametrize("error, notice", [(OperationCancelled, "Réponse interrompue"), (OperationTimedOut, "Délai maximal dépassé")])
def test_repl_input_cancel_then_partial_turn_notice_and_next_prompt(error, notice):
    reads = iter([KeyboardInterrupt(), "hi", "next", "quit"])
    output = io.StringIO()
    client = FakeClient(["partial", error("interrupted")], ["complete"])
    session = ChatSession(client, "model", "sys")

    def read(prompt):
        value = next(reads)
        if isinstance(value, BaseException):
            raise value
        return value

    def write(*args, **kwargs):
        print(*args, file=output, **kwargs)

    repl(session, read=read, write=write)
    text = output.getvalue()
    assert "interrompre la réponse" not in text
    assert f"partial\n{notice}" in text
    assert text.endswith("complete\n")
    assert [message.content for message in session.messages] == ["sys", "next", "complete"]
    assert client.calls[-1] == ["sys", "next"]


def test_operation_timeout_env_and_cli_precedence(monkeypatch):
    monkeypatch.setenv("SENSAI_OPERATION_TIMEOUT", "17")
    settings = Settings(_env_file=None)
    assert settings.operation_timeout == 17
    assert parse_args(settings, ["model"]).operation_timeout == 17
    assert parse_args(settings, ["model", "--operation-timeout", "2.5"]).operation_timeout == 2.5


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "-inf"])
def test_operation_timeout_rejects_invalid_cli_and_env_values(value, monkeypatch):
    from pydantic import ValidationError

    settings = Settings(_env_file=None)
    with pytest.raises(SystemExit):
        parse_args(settings, ["model", "--operation-timeout", value])
    monkeypatch.setenv("SENSAI_OPERATION_TIMEOUT", value)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
