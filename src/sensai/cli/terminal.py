"""Small POSIX terminal reader; no screen redraws while a reply streams."""
import codecs
import os
import select
import sys
import termios


class TerminalInput:
    def __init__(self, stdin=None, stdout=None):
        self.stdin = stdin if stdin is not None else sys.stdin
        self.stdout = stdout if stdout is not None else sys.stdout
        self.fd = None
        self.original = None
        self._pending = bytearray()
        try:
            if self.stdin.isatty():
                self.fd = self.stdin.fileno()
        except (AttributeError, OSError, ValueError):
            pass

    @property
    def interactive(self):
        return self.fd is not None

    def __enter__(self):
        if self.fd is not None:
            self.original = termios.tcgetattr(self.fd)
            mode = termios.tcgetattr(self.fd)
            mode[3] &= ~(termios.ICANON | termios.ECHO | termios.ISIG)
            mode[6][termios.VMIN] = 1
            mode[6][termios.VTIME] = 0
            try:
                termios.tcsetattr(self.fd, termios.TCSANOW, mode)
            except BaseException:
                termios.tcsetattr(self.fd, termios.TCSANOW, self.original)
                raise
        return self

    def __exit__(self, *exc):
        if self.original is not None:
            termios.tcsetattr(self.fd, termios.TCSANOW, self.original)

    def _byte(self):
        if self._pending:
            value = bytes(self._pending[:1])
            del self._pending[:1]
            return value
        return os.read(self.fd, 1)

    def _key(self):
        key = self._byte()
        if key != b"\x1b":
            return key
        if not self._pending and not select.select([self.fd], [], [], .05)[0]:
            return key
        next_byte = self._byte()
        if next_byte not in (b"[", b"O"):
            self._pending.extend(next_byte)
            return key
        # CSI/SS3: consume through its final byte, with a bounded wait.
        while self._pending or select.select([self.fd], [], [], .05)[0]:
            byte = self._byte()
            if not byte or b"@" <= byte <= b"~":
                break
        return None

    def read(self, prompt):
        self.stdout.write(prompt)
        self.stdout.flush()
        if self.fd is None:
            line = self.stdin.readline()
            if not line:
                raise EOFError
            return line.rstrip("\r\n")
        text = []
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        while True:
            key = self._key()
            if key is None:
                continue
            if not key or key == b"\x04" and not text:
                raise EOFError
            if key in (b"\x03", b"\x1b"):
                raise KeyboardInterrupt
            if key in (b"\r", b"\n"):
                self.stdout.write("\n")
                self.stdout.flush()
                return "".join(text)
            if key in (b"\x7f", b"\x08"):
                if text:
                    text.pop()
                    self.stdout.write("\b \b")
                decoder.reset()
            elif (key and key >= b" ") or key == b"\t":
                char = decoder.decode(key)
                text.extend(char)
                self.stdout.write(char)
            self.stdout.flush()

    def cancel_requested(self):
        if self.fd is None:
            return False
        while self._pending or select.select([self.fd], [], [], 0)[0]:
            if self._key() in (b"\x03", b"\x1b"):
                return True
        return False
