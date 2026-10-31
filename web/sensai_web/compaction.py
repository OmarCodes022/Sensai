"""The context budget (M2) in the page: the count after each turn, and summarizing older messages."""
from time import monotonic

from sensai.chat import compression
from sensai.chat.context import loaded_window, summary_cap
from sensai.core.cancellation import CancellationToken
from sensai.llm.ollama import OllamaClient
from sensai_web.errors import ApiError


def _ollama(app) -> bool:
    """The chat client under the guardrails wrapper is the real Ollama one (not a scripted test client)."""
    return isinstance(getattr(app.chat_client, "client", app.chat_client), OllamaClient)


def _summary_client(app):
    """The summary's own answer is capped at a quarter of the window; a scripted client is used as is."""
    if not _ollama(app):
        return None
    return OllamaClient(app.cfg.host, app.cfg.timeout, context_length=app.cfg.context_length,
                        num_predict=summary_cap(app.context.budget))


def _summarize(app, active, stop, tokens: int, emit) -> bool:
    """Condense the oldest messages between turns; a failure keeps the full history."""
    context, session = app.context, active.session
    cut = compression.choose_cut(session.messages)
    if cut is None:
        return False
    emit({"type": "compacting", "tokens": tokens, "budget": context.budget, "messages": cut - 1})
    token = CancellationToken(monotonic() + app.cfg.operation_timeout, stop.is_set)
    reasons = []
    if not compression.compress(session, cut, token, client=_summary_client(app),
                                max_chars=context.budget * 2, on_failure=reasons.append):
        cut_short = reasons and "token limit" in str(reasons[0])
        emit({"type": "warning", "code": "context",
              "message": "The summary hit its length limit, full history kept." if cut_short
              else "The summary failed, full history kept."})
        return False
    context.summaries += 1
    context.before_summary = tokens
    active.recorder.after_turn(session)
    emit({"type": "compacted", "messages": cut - 1, "summaries": context.summaries})
    return True


def after_turn(app, active, stop, emit) -> None:
    """Once a turn completed: take the count, learn the real window, summarize at 80%."""
    context = app.context
    usage = app.usage.last()
    context.start_turn()
    if usage is not None:
        context.on_usage(usage)
    tokens = context.end_turn(active.session.messages)
    context.learn(lambda: loaded_window(app.cfg.host, app.model)
                  if _ollama(app) else None)
    if compression.should_compress(tokens, context.budget):
        _summarize(app, active, stop, tokens, emit)


def compact(app) -> dict:
    """POST /api/context/compact: summarize now, whatever the count."""
    stop, active = app.begin_turn()
    events = []
    try:
        context = app.context
        before = context.last_tokens if context.last_tokens is not None \
            else compression.estimate_tokens(active.session.messages)
        if compression.choose_cut(active.session.messages) is None:
            raise ApiError(409, "nothing_to_compact", "Nothing to compact yet: too few older messages.")
        old = list(active.session.messages)
        if not _summarize(app, active, stop, before, events.append):
            raise ApiError(502, "summary_failed", events[-1]["message"])
        after = compression.after_summary(before, old, active.session.messages)
        context.last_tokens, context.before_summary = after, None
        context.saved += max(before - after, 0)
        return {"before": before, "after": after, "messages": events[-1]["messages"], **context.as_dict()}
    finally:
        app.end_turn()
