"""Turn stored messages into the display items the page renders (pure functions)."""
from collections.abc import Mapping, Sequence

from sensai.chat.blocks import split_block
from sensai.chat.saved_sessions import TOOL_PROTOCOL_PREFIXES, user_messages
from sensai.core.messages import Message

HISTORY_WIDTH = 100
ROUND_LIMIT_NOTE = "\nTool round limit reached. Give a final answer without tools."
REFUSED = "tool approval refused"


def _tool_result(entry: dict, content: str) -> None:
    head, _, body = content.partition(":\n")
    body = body.removesuffix(ROUND_LIMIT_NOTE)
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
                _tool_result(pending, message.content)
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
