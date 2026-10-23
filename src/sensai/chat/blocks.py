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


def _closed_object_end(reply, offset):
    depth, quoted, escaped = 0, False, False
    for index in range(offset, len(reply)):
        char = reply[index]
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index + 1
    return None


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
    """Hold possible final blocks; release decoded objects followed by text."""

    def __init__(self):
        self._reply = ""
        self._printed = 0

    def feed(self, chunk: str) -> str:
        self._reply += chunk
        start = _START.search(self._reply, self._printed)
        safe = len(self._reply)
        while start is not None:
            offset = start.start()
            try:
                _, end = _DECODER.raw_decode(self._reply, offset)
            except (ValueError, RecursionError):
                end = _closed_object_end(self._reply, offset)
                if end is None:
                    safe = offset
                    break
                # A closed invalid object cannot become the final protocol block.
                start = _START.search(self._reply, end)
                continue
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
