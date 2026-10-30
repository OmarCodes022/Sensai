"""Turn stored messages into the display items the page renders (pure functions)."""
import re
from collections.abc import Mapping, Sequence

from sensai.chat.blocks import split_block
from sensai.chat.saved_sessions import TOOL_PROTOCOL_PREFIXES, user_messages
from sensai.core.messages import Message
from sensai.sandbox import FIX_IT, RUN_PYTHON

HISTORY_WIDTH = 100
ROUND_LIMIT_NOTE = "\nTool round limit reached. Give a final answer without tools."
REFUSED = "tool approval refused"
# What run_with_tools adds around the result of a tool with a call limit (T21).
ATTEMPT = re.compile(r"Attempt ([0-9]+) of ([0-9]+) · ")
LAST_ATTEMPT = re.compile(r"\nThis was the last attempt: answer with this result or error, without calling \S+ again\.\Z")
STOPPED = re.compile(r"Stopped after ([0-9]+) attempts?: ")


def for_page(name: str, text: str | None) -> str | None:
    """A tool's result as the creator sees it: run_python's report without the line meant for the model."""
    if name != RUN_PYTHON.name or text is None:
        return text
    return "" if text == FIX_IT else text.removesuffix(f"\n{FIX_IT}")


def _attempts(entry: dict, body: str, stopped_before: int) -> str:
    """Moves the attempt number of a limited tool's result into the entry; returns the bare result.

    A stopped call is numbered by its place in the question: after the limit, plus earlier stopped calls.
    """
    if (match := ATTEMPT.match(body)) is not None:
        entry["attempt"], entry["max_attempts"] = int(match.group(1)), int(match.group(2))
        return LAST_ATTEMPT.sub("", body[match.end():])
    if (match := STOPPED.match(body)) is not None:
        limit = int(match.group(1))
        entry["attempt"], entry["max_attempts"] = limit + stopped_before + 1, limit
    return body


def _stopped(entry: dict) -> bool:
    return "attempt" in entry and entry["attempt"] > entry["max_attempts"]


def _tool_result(entry: dict, content: str, earlier: Sequence[dict] = ()) -> None:
    head, _, body = content.partition(":\n")
    stopped_before = sum(1 for other in earlier if other["name"] == entry["name"] and _stopped(other))
    body = for_page(entry["name"], _attempts(entry, body.removesuffix(ROUND_LIMIT_NOTE), stopped_before))
    entry["ok"] = head.startswith("Tool result from ")
    if entry["ok"]:
        entry["output"] = body
    else:
        entry["error"] = body
        entry["refused"] = body == REFUSED


def display_items(messages: Sequence[Message], persona: str | None,
                  times: Mapping[int, tuple[str, str]] | None = None) -> list[dict]:
    """User and assistant items; tool rounds become entries of the assistant item they belong to.

    `times` maps a turn number to (started, finished) and becomes each item's `at`.
    """
    times = times or {}
    items: list[dict] = []
    reply: dict | None = None
    pending: dict | None = None
    number = 0
    for message in messages:
        if message.role == "user" and message.content.startswith(TOOL_PROTOCOL_PREFIXES):
            if pending is not None:
                _tool_result(pending, message.content, reply["tools"][:-1] if reply else ())
                pending = None
        elif message.role == "user":
            number += 1
            items.append({"kind": "user", "n": number, "text": message.content})
            if number in times:
                items[-1]["at"] = times[number][0]
            reply = None
        elif message.role == "assistant":
            if reply is None:
                reply = {"kind": "assistant", "text": "", "persona": persona, "usage": None, "tools": []}
                if number in times:
                    reply["at"] = times[number][1]
                items.append(reply)
            visible, block = split_block(message.content)
            reply["text"] += visible
            if block is not None and "tool" in block:
                arguments = block.get("arguments")
                pending = {"kind": "tool", "id": f"c{len(reply['tools']) + 1}", "name": str(block["tool"]),
                           "arguments": arguments if isinstance(arguments, dict) else {},
                           "round": len(reply["tools"]) + 1, "ok": None}
                reply["tools"].append(pending)
    for item in items:
        if item["kind"] == "assistant":
            item["text"] = item["text"].strip()
    return items


def history_line(text: str) -> str:
    lines = text.strip().splitlines()
    line = lines[0].strip() if lines else ""
    if len(line) > HISTORY_WIDTH:
        return line[:HISTORY_WIDTH].rstrip() + " …"
    return line + " …" if len(lines) > 1 else line


def history(messages: Sequence[Message]) -> list[dict]:
    return [{"n": n, "text": history_line(text)} for n, text in enumerate(user_messages(messages), 1)]
