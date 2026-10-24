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
_START = re.compile(r"(?m)^\{")


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
    """Extract only an object starting at column zero and ending the reply."""
    for start in _START.finditer(reply):
        try:
            block, end = _DECODER.raw_decode(reply, start.start())
        except (ValueError, RecursionError):
            continue
        if isinstance(block, dict) and not reply[end:].strip():
            return reply[:start.start()], block
    return reply, None


class BlockReader:
    """Hold a ``{`` line while it may still become the final block, else release it."""

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
        safe = len(self._reply)
        while start is not None:
            offset = start.start()
            try:
                _, end = _DECODER.raw_decode(self._reply, offset)
            except json.JSONDecodeError as exc:
                cut_string = exc.msg.startswith("Unterminated string")
                if (cut_string or exc.pos >= len(self._reply)
                        or _PARTIAL_TOKEN.fullmatch(self._reply, exc.pos)):
                    safe = offset  # More text may still complete this object.
                    if cut_string:
                        self._string = exc.pos + 1
                    break
                end = offset + 1  # The error is final: try the next line.
            except (ValueError, RecursionError):
                end = offset + 1  # NaN/Infinity, nonfinite numbers, deep nesting.
            else:
                if not self._reply[end:].strip():
                    safe = offset
                    break
            start = _START.search(self._reply, end)
        visible = self._reply[self._printed:safe]
        self._printed = safe
        return visible

    def finish(self) -> tuple[str, dict | None]:
        """Return full visible text; callers print its not-yet-emitted suffix."""
        return split_block(self._reply)
