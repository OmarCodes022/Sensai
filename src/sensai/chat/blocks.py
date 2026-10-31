"""Read a final strict JSON object without displaying its protocol payload."""

import json
import math
import re


def _finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("nonfinite JSON number")
    return number


def _invalid_constant(value):
    raise ValueError("invalid JSON constant")


_DECODER = json.JSONDecoder(parse_constant=_invalid_constant, parse_float=_finite_float)
# An object at the start of a line, maybe indented, maybe after a code fence such as ```json or ```tool_code.
_START = re.compile(r"(?m)^[ \t]*(```[\w.+-]*[ \t]*\r?\n[ \t]*)?\{")
# The end of the reply, while it may still grow into such a start.
_OPENING = re.compile(r"(?m)^[ \t]*(?:`{1,2}|```[\w.+-]*[ \t]*\r?\n?[ \t]*)?\Z")


# Where a decode error points when only the end of the buffer is missing (besides
# an unterminated string): a cut \uXXXX escape (or surrogate pair), number or literal.
_PARTIAL_TOKEN = re.compile(r'''
    \\?u[0-9a-fA-F]{0,4}(?:\\u?[0-9a-fA-F]{0,3})?
  | -|\.|[eE][-+]?
  | t(?:ru?)?|f(?:a(?:ls?)?)?|n(?:ul?)?
''', re.X)
_STRING_BODY = re.compile(r'(?:[^"\\\x00-\x1f]+|\\["\\/bfnrt]|\\u[0-9a-fA-F]{4})*')
_CUT_ESCAPE = re.compile(r'\\(?:u[0-9a-fA-F]{0,3})?')


def split_block(reply: str) -> tuple[str, dict | None]:
    """Extract only an object ending the reply.

    At column zero any object counts. Indented or inside a code fence, which
    models often write instead, only a tool call does: other JSON stays visible.
    """
    for start in _START.finditer(reply):
        try:
            block, end = _DECODER.raw_decode(reply, start.end() - 1)
        except (ValueError, RecursionError):
            continue
        rest = reply[end:].strip()
        if not isinstance(block, dict) or not (not rest or (start.group(1) and rest == "```")):
            continue
        if start.end() - start.start() == 1 or "tool" in block:
            return reply[:start.start()], block
    return reply, None


def _held_opening(reply: str, printed: int) -> int:
    """Where the unprinted end of the reply may still open a block (two lines at most)."""
    last = reply.rfind("\n", printed)
    previous = reply.rfind("\n", printed, last) if last >= 0 else -1
    opening = _OPENING.search(reply, previous + 1 if previous >= 0 else printed)
    return opening.start() if opening else len(reply)


class BlockReader:
    """Hold a possible block start while it may still become the final block, else release it."""

    def __init__(self):
        self._reply = ""
        self._printed = 0
        self._string = None  # Scan position inside a held block's unterminated string.

    def feed(self, chunk: str) -> str:
        self._reply += chunk
        if self._string is not None:
            # Long string arguments: check only the new text, not the whole block again.
            scan = _STRING_BODY.match(self._reply, self._string).end()
            if scan == len(self._reply) or _CUT_ESCAPE.fullmatch(self._reply, scan):
                self._string = scan
                return ""
            self._string = None
        start = _START.search(self._reply, self._printed)
        safe = None
        while start is not None:
            offset = start.end() - 1
            try:
                _, end = _DECODER.raw_decode(self._reply, offset)
            except json.JSONDecodeError as exc:
                cut_string = exc.msg.startswith("Unterminated string")
                if (cut_string or exc.pos >= len(self._reply)
                        or _PARTIAL_TOKEN.fullmatch(self._reply, exc.pos)):
                    safe = start.start()  # More text may still complete this object.
                    if cut_string:
                        self._string = exc.pos + 1
                    break
                end = offset + 1  # The error is final: try the next line.
            except (ValueError, RecursionError):
                end = offset + 1  # NaN/Infinity, nonfinite numbers, deep nesting.
            else:
                rest = self._reply[end:].strip()
                if not rest or (start.group(1) and "```".startswith(rest)):
                    safe = start.start()
                    break
            start = _START.search(self._reply, end)
        if safe is None:
            safe = _held_opening(self._reply, self._printed)
        visible = self._reply[self._printed:safe]
        self._printed = safe
        return visible

    @property
    def reply(self) -> str:
        """Everything received so far, block included."""
        return self._reply

    def finish(self) -> tuple[str, dict | None]:
        """Return full visible text; callers print its not-yet-emitted suffix."""
        return split_block(self._reply)
