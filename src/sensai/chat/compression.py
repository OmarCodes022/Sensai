"""Summarize the oldest messages when the context nears its token budget (M2)."""
import json
from time import monotonic

from sensai import usage_log
from sensai.core.cancellation import CancellationToken
from sensai.core.errors import SensaiError
from sensai.core.messages import Message
from sensai.llm.client import close_stream

THRESHOLD = 0.8
KEEP_LAST = 4
MIN_TO_SUMMARIZE = 2
SUMMARY_PREFIX = "Summary of earlier conversation:"
SUMMARY_REQUEST = (
    "Summarize the conversation above in a compact block. Keep every name, product, "
    "date, number, decision and the creator's preferences. Reply with the summary only."
)


def should_compress(tokens: int, budget: int) -> bool:
    return tokens >= THRESHOLD * budget


def estimate_tokens(messages: list[Message]) -> int:
    """Fallback when Ollama reports no count: about four characters per token."""
    return sum(len(m.content) for m in messages) // 4


def after_summary(before: int, old: list[Message], new: list[Message]) -> int:
    """The count once a summary replaced messages: `before` minus the estimated tokens it removed."""
    return max(before - (estimate_tokens(old) - estimate_tokens(new)), 0)


def is_tool_call(message: Message) -> bool:
    """An assistant reply ending with a {"tool": ...} block (T18); its result comes next."""
    if message.role != "assistant":
        return False
    text = message.content.rstrip()
    start = text.rfind("\n{") + 1 if not text.startswith("{") else 0
    try:
        block = json.loads(text[start:])
    except ValueError:
        return False
    return isinstance(block, dict) and "tool" in block


def choose_cut(messages: list[Message]) -> int | None:
    """End index of the messages to summarize (messages[1:cut]); None if too few."""
    cut = len(messages) - KEEP_LAST
    # Never keep a tool result whose call was summarized: keep the call too.
    while cut > 1 and is_tool_call(messages[cut - 1]):
        cut -= 1
    if cut - 1 < MIN_TO_SUMMARIZE:
        return None
    return cut


def compress(session, cut: int, cancellation: CancellationToken | None = None, *, client=None,
             max_chars: int | None = None, on_failure=None) -> bool:
    """Replace messages[1:cut] by one summary; on any failure keep the history unchanged.

    `client` (default: the session's) can cap the summary's length; `max_chars` trims the
    transcript sent so it fits the window; `on_failure(error)` hears why a summary failed.
    """
    start, earlier = 1, ""
    first = session.messages[1]
    if first.role == "assistant" and first.content.startswith(SUMMARY_PREFIX):
        # Keep an earlier summary verbatim: re-summarizing it loses facts on small models.
        start, earlier = 2, first.content[len(SUMMARY_PREFIX):].strip() + "\n"
    transcript = "\n\n".join(f"{m.role}: {m.content}" for m in session.messages[start:cut])
    if max_chars is not None and len(transcript) > max_chars:
        transcript = "[the oldest part was cut to fit]\n" + transcript[-max_chars:]
    # Instruction after the delimited transcript: small models otherwise continue the chat.
    request = [Message(role="user",
                       content=f"Conversation:\n<<<\n{transcript}\n>>>\n\n{SUMMARY_REQUEST}")]
    stream, started = None, monotonic()
    try:
        stream = (client or session.client).stream(session.model, request, cancellation=cancellation)
        chunks = []
        for chunk in stream:
            if cancellation is not None:
                cancellation.raise_if_cancelled()
            chunks.append(chunk)
        if cancellation is not None:
            cancellation.raise_if_cancelled()
    except (SensaiError, KeyboardInterrupt) as exc:  # failed, timed out or cancelled
        usage_log.record("summary", session.model, f"{cut - 1} older messages", latency_ms=(monotonic() - started) * 1000,
                         error="cancelled" if isinstance(exc, KeyboardInterrupt) else str(exc))
        if on_failure is not None:
            on_failure(exc)
        return False
    finally:
        try:
            close_stream(stream)
        except SensaiError:
            pass
    summary = "".join(chunks).strip()
    usage_log.record("summary", session.model, f"{cut - 1} older messages", summary,
                     latency_ms=(monotonic() - started) * 1000, error=None if summary else "empty summary")
    if not summary:
        return False
    # Single assignment at the very end: nothing is lost if anything above failed.
    session.messages[1:cut] = [Message(role="assistant",
                                       content=f"{SUMMARY_PREFIX}\n{earlier}{summary}")]
    return True
