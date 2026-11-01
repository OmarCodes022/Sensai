"""The semantic cache (A6) and the picked examples (A7) in the terminal."""
from time import monotonic

from sensai.chat.examples import turns
from sensai.core.messages import Message


def answer_from_cache(cache, scope_id: str, text: str, session, write, recorder) -> bool:
    """True when `text` was answered from the cache (shown, added and saved like a normal turn)."""
    started = monotonic()
    hit = cache.lookup(scope_id, text)
    if cache.off:  # Only a session's first question is looked up, so this is said once.
        write(f"warning: {cache.off}")
    if hit is None:
        return False
    write(hit.answer)
    write(f"({hit.label()} · {monotonic() - started:.1f} s)")
    session.messages += [Message(role="user", content=text), Message(role="assistant", content=hit.answer)]
    if recorder is not None:
        recorder.after_turn(session)
    return True


def remember(cache, scope_id: str, text: str, session) -> None:
    """After a completed first turn: keep its final answer for questions like it."""
    if session.messages and session.messages[-1].role == "assistant":
        cache.store(scope_id, text, session.messages[-1].content)


def use_examples(picker, text: str, write) -> tuple:
    """The example turns for this question, after saying which were used; a failing picker warns once."""
    was_off, picked = picker.off, picker.pick(text)
    if picker.off and not was_off:
        write(f"warning: {picker.off}")
    if picked:
        write(f"Examples used: {', '.join(e['id'] for e in picked)}")
    return turns(picked)
