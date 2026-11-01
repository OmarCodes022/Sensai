"""The semantic cache (A6) in the page: a session's first question may be answered from it at once."""
from time import monotonic

from sensai.chat.saved_sessions import user_messages
from sensai.core.messages import Message
from sensai.llm.embeddings import OllamaEmbeddingAdapter
from sensai.memory.semantic_cache import SemanticCache, scope


def make_cache(settings) -> SemanticCache | None:
    if not settings.cache:
        return None
    return SemanticCache(settings.cache_path, OllamaEmbeddingAdapter(settings.embed_model, host=settings.host).embed,
                         settings.cache_threshold)


def first_question(app, active) -> bool:
    return app.cache is not None and not user_messages(active.session.messages)


def _scope(app, active) -> str:
    return scope(app.cfg.creator, app.model, active.session.messages[0].content)


def serve(app, active, text: str, emit) -> bool:
    """True when `text` was answered from the cache: the reply, a `cached` event, and the turn in the session."""
    started = monotonic()
    hit = app.cache.lookup(_scope(app, active), text)
    if app.cache.off:
        emit({"type": "warning", "code": "cache", "message": app.cache.off})
    if hit is None:
        return False
    emit({"type": "text", "delta": hit.answer})
    emit({"type": "cached", "question": hit.question, "similarity": round(hit.similarity, 3),
          "seconds": round(monotonic() - started, 2)})
    active.session.messages += [Message(role="user", content=text), Message(role="assistant", content=hit.answer)]
    return True


def remember(app, active, text: str) -> None:
    last = active.session.messages[-1]
    if last.role == "assistant":
        app.cache.store(_scope(app, active), text, last.content)
