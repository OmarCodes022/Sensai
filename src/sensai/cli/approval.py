"""Terminal approval prompt shown before a tool that needs consent runs."""
import json
import re

from sensai.core.ports import ApprovalDecision, ApprovalRequest

_LONE_CR = re.compile("\r(?!\n)")


def _escape(char):
    code = ord(char)
    if code < 0x100:
        return f"\\x{code:02x}"
    return f"\\u{code:04x}" if code < 0x10000 else f"\\U{code:08x}"


def sanitize(text, keep="\t"):
    """Escape every non-printable character (controls, bidi, invisible, surrogates)."""
    return "".join(char if char.isprintable() or char in keep else _escape(char)
                   for char in text)


def _split(text):
    # Python ends a source line at a lone \r too: show the break, and the escaped \r.
    return [sanitize(line) for line in _LONE_CR.sub("\r\n", text).split("\n")]


def _compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _arguments(resource):
    """Yield (header, lines) per argument; header None means lines stand alone."""
    try:
        arguments = json.loads(resource)
    except (ValueError, RecursionError):
        arguments = None
    if not isinstance(arguments, dict):
        yield None, ["  " + line for line in _split(resource)]
        return
    for key, value in arguments.items():
        if isinstance(value, str):
            yield f"  {sanitize(key, keep='')}:", ["    " + line for line in _split(value)]
        else:
            yield None, [f"  {sanitize(key, keep='')}: {sanitize(_compact(value))}"]


class TerminalApproval:
    """Ask on the terminal before a tool runs; satisfies ApprovalPort."""

    def __init__(self, read_key, write=print, *, preview_lines: int = 6,
                 line_width: int = 160) -> None:
        self._read_key = read_key
        self._write = write
        self._preview_lines = preview_lines
        self._line_width = line_width

    def _cut(self, line):
        if len(line) <= self._line_width:
            return line, False
        return line[:max(self._line_width - 1, 0)] + "…", True

    def _preview(self, resource):
        lines, budget, hidden, cut = [], self._preview_lines, 0, False
        for header, values in _arguments(resource):
            if budget <= 0:
                hidden += len(values)
                continue
            if header is not None:
                header, was_cut = self._cut(header)
                lines.append(header)
                cut = cut or was_cut
            for value in values:
                if budget <= 0:
                    hidden += 1
                    continue
                budget -= 1
                value, was_cut = self._cut(value)
                lines.append(value)
                cut = cut or was_cut
        if hidden:
            lines.append(f"    … (+{hidden} more line{'s' if hidden != 1 else ''})")
        return lines, bool(hidden or cut)

    def request(self, request: ApprovalRequest) -> ApprovalDecision:
        lines, incomplete = self._preview(request.resource)
        self._write("")
        self._write(f"Run {sanitize(request.action, keep='')}?")
        for line in lines:
            self._write(line)
        try:
            if not incomplete:
                return ApprovalDecision(self._read_key("[y] run · [n] refuse ", "yn", "n") == "y")
            answer = self._read_key("[y] run · [n] refuse · [v] view all ", "ynv", "n")
            if answer == "v":
                for header, values in _arguments(request.resource):
                    for line in ([header] if header is not None else []) + values:
                        self._write(line)
                answer = self._read_key("[y] run · [n] refuse ", "yn", "n")
        except EOFError:
            return ApprovalDecision(False)
        return ApprovalDecision(answer == "y")
