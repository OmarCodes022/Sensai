"""cli.terminal.TerminalInput on a real POSIX pty, without an Ollama server."""

from contextlib import contextmanager
import io
import json
import os
import pty
import termios
import threading
import time

import pytest

from sensai.cli.approval import TerminalApproval
from sensai.cli.terminal import TerminalInput
from sensai.core.ports import ApprovalRequest


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


def test_terminal_comparison_masks_only_pendin(monkeypatch):
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


def read_key_with(content, choices="ynv", default="n"):
    with terminal() as (reader, master):
        timer = feed(master, content)
        try:
            return reader.read_key("? ", choices, default)
        finally:
            timer.join()


@pytest.mark.parametrize("content, expected", [
    (b"y", "y"), (b"n", "n"), (b"v", "v"), (b"Y", "y"), (b"V", "v"),
    (b"\r", "n"), (b"\n", "n"), (b"\x1b[Ax\x1b[B\x1bOP\tq7y", "y"),
    ("é→y".encode(), "y"),
])
def test_read_key_returns_single_choice_without_enter(content, expected):
    assert read_key_with(content) == expected


def test_read_key_echoes_choice_then_newline():
    master, slave = pty.openpty()
    stdin = os.fdopen(os.dup(slave), "r", encoding="utf-8")
    output = io.StringIO()
    watchdog = threading.Timer(2, os.write, (master, b"\x04"))
    try:
        with TerminalInput(stdin=stdin, stdout=output) as reader:
            watchdog.start()
            for prompt, content in (("Run? ", b"zY"), ("Again? ", b"\r")):
                timer = feed(master, content)
                try:
                    reader.read_key(prompt, "yn", "n")
                finally:
                    timer.join()
        assert output.getvalue() == "Run? y\nAgain? n\n"
    finally:
        watchdog.cancel()
        if watchdog.ident is not None:
            watchdog.join()
        stdin.close()
        os.close(master)
        os.close(slave)


@pytest.mark.parametrize("key", [b"\x03", b"\x1b"])
def test_read_key_cancel_keys_interrupt(key):
    with pytest.raises(KeyboardInterrupt):
        read_key_with(b"x" + key + b"y")


def test_read_key_ctrl_d_is_eof():
    with pytest.raises(EOFError):
        read_key_with(b"\x04y")


def test_read_key_ignores_keys_typed_before_the_prompt():
    with terminal() as (reader, master):
        os.write(master, b"y")
        time.sleep(0.05)
        timer = feed(master, b"n")
        try:
            assert reader.read_key("? ", "yn", "y") == "n"
        finally:
            timer.join()


def test_read_key_ctrl_c_typed_before_the_prompt_interrupts():
    with terminal() as (reader, master):
        os.write(master, b"\x03")
        time.sleep(0.05)
        with pytest.raises(KeyboardInterrupt):
            reader.read_key("? ", "yn", "y")


@pytest.mark.parametrize("line, expected", [
    ("y\n", "y"), ("  Yes\n", "y"), ("\n", "n"), ("   \n", "n"), ("x\n", "n"),
    ("v", "v"), ("N\n", "n"),
])
def test_read_key_non_tty_reads_a_line(line, expected):
    output = io.StringIO()
    reader = TerminalInput(stdin=io.StringIO(line), stdout=output)
    assert reader.read_key("? ", "ynv", "n") == expected
    assert output.getvalue() == "? "


def test_read_key_non_tty_eof_and_bad_default():
    reader = TerminalInput(stdin=io.StringIO(""), stdout=io.StringIO())
    with pytest.raises(EOFError):
        reader.read_key("? ", "yn", "n")
    for default in ("x", "", "yn"):
        with pytest.raises(ValueError):
            reader.read_key("? ", "yn", default)


@pytest.mark.parametrize("keys, approved", [((b"v", b"y"), True), ((b"\r",), False)])
def test_real_read_key_drives_terminal_approval(keys, approved):
    code = "\n".join(f"print({i})" for i in range(10))
    lines = []
    with terminal() as (reader, master):
        answers = iter(keys)

        def read_key(prompt, choices, default):
            timer = feed(master, next(answers))
            try:
                return reader.read_key(prompt, choices, default)
            finally:
                timer.join()

        approval = TerminalApproval(read_key, lines.append)
        request = ApprovalRequest("run_python", json.dumps({"code": code}), "Run code.")
        assert approval.request(request).approved is approved
        assert next(answers, None) is None
    assert lines[-1] == ("    print(9)" if approved else "    … (+4 more lines)")
