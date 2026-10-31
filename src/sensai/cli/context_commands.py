"""The context budget in the terminal (M2): the status line, /context, and summarizing on demand or at 80%."""
from sensai.chat import compression
from sensai.chat.context import ContextState


def summarize(session, context: ContextState, tokens: int, write, recorder, token, summary_client=None,
              force: bool = False) -> bool:
    """Between turns only: condense the oldest messages; a failure keeps the full history."""
    cut = compression.choose_cut(session.messages)
    if cut is None:
        if force:
            write("Nothing to compact yet: too few older messages.")
        return False
    write(f"{context.line(tokens)}, summarizing {cut - 1} older messages…")
    reasons = []
    client = summary_client(context.budget) if summary_client is not None else None
    # The transcript sent is trimmed to about half the window (characters / 4 is about one token).
    if not compression.compress(session, cut, token, client=client, max_chars=context.budget * 2,
                                on_failure=reasons.append):
        cut_short = reasons and "token limit" in str(reasons[0])
        write("warning: the summary hit its length limit, full history kept" if cut_short
              else "warning: summary failed, full history kept")
        return False
    context.summaries += 1
    context.before_summary = tokens
    if recorder is not None:
        recorder.after_turn(session)
    return True


def compact(session, context: ContextState, write, recorder, token, summary_client=None) -> None:
    """/compact: summarize now, whatever the count, and show the tokens before and after."""
    before = context.last_tokens if context.last_tokens is not None else compression.estimate_tokens(session.messages)
    old = list(session.messages)
    if summarize(session, context, before, write, recorder, token, summary_client, force=True):
        after = compression.after_summary(before, old, session.messages)
        context.last_tokens = after
        context.saved += max(before - after, 0)
        context.before_summary = None
        write(f"Compacted: about {before:,} -> {after:,} tokens.")
