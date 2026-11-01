"""/think over HTTP: the bounded plan, act, draft, check, revise loop as stream events."""
from time import monotonic
from uuid import uuid4

from sensai.chat.reasoning import Section, think
from sensai.core.cancellation import CancellationToken, OperationCancelled, OperationTimedOut
from sensai.core.errors import GuardrailRefused, LLMError, SensaiError
from sensai.core.messages import Message
from sensai.chat.saved_sessions import user_messages
from sensai.sandbox import remove_stale_folders
from sensai_web.app import ActiveSession, WebApp, now
from sensai_web.approvals import WebApproval
from sensai_web.errors import llm_failure
from sensai_web.facts import settle
from sensai_web.guard import screen, stopped
from sensai.rag_advanced import make_ranker
from sensai_web.questions import WebForm
from sensai_web import websearch
from sensai_web.tools import ObservedRegistry
from sensai_web.turn import Emit, _add, _log, _persist

SKIPPED = ("Act", "Observe")  # Tool rounds already reach the page as tool cards.


def _writer(emit: Emit):
    """Sections become bold headings in the reply text; the tool lines under Act and Observe are dropped."""
    skip = False

    def write(item) -> None:
        nonlocal skip
        if isinstance(item, Section):
            skip = item.title in SKIPPED
            if not skip:
                emit({"type": "text", "delta": f"\n\n**{item.title}**\n\n"})
        elif skip:
            skip = False
        elif item:
            emit({"type": "text", "delta": item})
    return write


def run_think(app: WebApp, active: ActiveSession, stop, request: str, emit: Emit) -> None:
    """Answer `request` step by step. Only the request and the final answer join the conversation."""
    cfg, session = app.cfg, active.session
    started_at = now()
    turn_id = f"t{uuid4().hex[:8]}"
    number = len(user_messages(session.messages)) + 1
    emit({"type": "turn_start", "turn_id": turn_id, "model": cfg.model, "persona": active.persona_id,
          "number": number, "budget_seconds": cfg.operation_timeout, "think": True})
    request = screen(app, request, emit)
    if request is None:  # Refused before the model: nothing is sent, kept or saved.
        emit({"type": "done", "status": "completed", "turn_id": turn_id})
        return "blocked"
    for notice in app.refresh_prompt(active):
        emit({"type": "warning", "code": "documents", "message": notice})
    approval = WebApproval(app.approvals, emit, stop, turn_id)
    app.memory.drop()
    if app.web is not None:
        app.web.results.clear()  # Sources are listed per reply.
    registry = ObservedRegistry(approval, emit, app.data.path, app.meta_dir, app.docs, app.memory, app.files,
                              WebForm(app.questions, emit, stop, turn_id, approval), app.web,
                              make_ranker(app.checker, app.model) if app.rag_mode == "advanced" else None,
                              app.mcp)
    write = _writer(emit)

    def new_token():  # Each step gets its own deadline; stop cancels them all.
        return CancellationToken(monotonic() + cfg.operation_timeout, stop.is_set)

    status, result = None, None
    stream = think(session, registry, request, app.checker, new_token=new_token, emit=write)
    try:
        while True:
            try:
                write(next(stream))
            except StopIteration as done:
                result = done.value
                break
        status = "completed"
    except OperationCancelled:
        status = "interrupted"
    except OperationTimedOut:
        status = "timed_out"
    except LLMError as exc:
        emit({"type": "error", **llm_failure(exc, cfg.model)})
    except GuardrailRefused as exc:
        stopped(emit, exc)
        status = "blocked"
    except SensaiError as exc:
        emit({"type": "error", "code": "error", "message": str(exc), "hint": None})
    finally:
        stream.close()
        registry.close()
        remove_stale_folders()
    settle(app, active, status == "completed", emit)  # Fact changes count only for a completed reply.
    if status == "blocked":  # The reply was stopped: the page drops it, nothing is saved.
        emit({"type": "done", "status": "completed", "turn_id": turn_id})
        return status
    if status is None:
        return
    if status == "completed":
        websearch.sources(app, emit)
        session.messages.append(Message(role="user", content=request))
        session.messages.append(Message(role="assistant", content=result.answer))
        usage = app.usage.summary()
        emit({"type": "usage", **usage})
        active.prompt_tokens = _add(active.prompt_tokens, usage["prompt_tokens"])
        active.output_tokens = _add(active.output_tokens, usage["output_tokens"])
        active.last_prompt_tokens = usage["prompt_tokens"]
        _persist(app, active, emit, stop, cfg.operation_timeout)
        active.updated_at = now()
        if active.recorder.saved:
            app.times.record(active.recorder.session_id, number, started_at, active.updated_at, usage)
    _log(app, active, f"/think {request}", status, None if status == "completed" else status, registry.used)
    emit({"type": "done", "status": status, "turn_id": turn_id})
