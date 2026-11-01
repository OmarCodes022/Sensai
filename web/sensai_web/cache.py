"""The semantic cache (A6) and the picked examples (A7) in the page."""
from time import monotonic

from sensai.chat.examples import ExamplePicker, turns
from sensai.chat.saved_sessions import user_messages
from sensai.core.messages import Message
from sensai.llm.embeddings import OllamaEmbeddingAdapter
from sensai.memory.semantic_cache import SemanticCache, scope


def make_cache(settings) -> SemanticCache | None:
    if not settings.cache:
        return None
    return SemanticCache(settings.cache_path, OllamaEmbeddingAdapter(settings.embed_model, host=settings.host).embed,
                         settings.cache_threshold)


def make_examples(settings) -> ExamplePicker | None:
    return ExamplePicker(OllamaEmbeddingAdapter(settings.embed_model, host=settings.host).embed) if settings.examples else None


def examples_for(app, text: str, emit) -> tuple:
    """The example turns for this question (an `examples` event names them); a failing picker warns once."""
    was_off, picked = app.examples.off, app.examples.pick(text)
    if app.examples.off and not was_off:
        emit({"type": "warning", "code": "examples", "message": app.examples.off})
    if picked:
        emit({"type": "examples", "ids": [e["id"] for e in picked]})
    return turns(picked)


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
