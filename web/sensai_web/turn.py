"""One chat turn as stream events: text, tool calls, approvals, usage, saving, done."""
from collections.abc import Callable
from time import monotonic
from uuid import uuid4

from sensai.chat import saved_sessions
from sensai.chat.saved_sessions import user_messages
from sensai.core.cancellation import CancellationToken, OperationCancelled, OperationTimedOut
from sensai.core.errors import GuardrailRefused, LLMError, SensaiError
from sensai.sandbox import remove_stale_folders
from sensai.tools import run_with_tools
from sensai_web.app import ActiveSession, WebApp, now
from sensai_web.approvals import WebApproval
from sensai_web.compaction import after_turn
from sensai_web.errors import llm_failure
from sensai_web.facts import settle
from sensai_web.guard import screen, stopped
from sensai.rag_advanced import make_ranker
from sensai_web.questions import WebForm
from sensai_web import websearch
from sensai_web.tools import INVALID, ObservedRegistry

Emit = Callable[[dict], None]


def _add(total: int | None, value: int | None) -> int | None:
    return total if value is None else (total or 0) + value


def _persist(app: WebApp, active: ActiveSession, emit: Emit, stop, budget: float) -> None:
    """Save the finished turn and report it; storage problems are warnings, never a failed turn."""
    recorder = active.recorder
    saved_before, title_before = recorder.saved, recorder.title
    recorder.write = lambda message: emit({"type": "warning", "code": "storage",
                                           "message": message.removeprefix("error: ")})

    def titler(first_user: str, first_answer: str) -> str | None:
        token = CancellationToken(monotonic() + min(saved_sessions.TITLE_TIMEOUT, budget), stop.is_set)
        return saved_sessions.generate_title(app.title_client, app.model, first_user, first_answer, token)

    recorder.titler = titler
    recorder.after_turn(active.session)
    if recorder.saved and not saved_before:
        active.created_at = now()
        emit({"type": "saved", "session_id": recorder.session_id})
    if recorder.title and recorder.title != title_before:
        emit({"type": "title", "title": recorder.title})


def run_turn(app: WebApp, active: ActiveSession, stop, text: str, emit: Emit) -> str | None:
    """Answer `text` on the active session. Ends with `done`, or with `error` when the turn failed.

    Returns the final status (completed, interrupted, timed_out), or None after an error.
    """
    cfg, session = app.cfg, active.session
    started_at = now()
    turn_id = f"t{uuid4().hex[:8]}"
    number = len(user_messages(session.messages)) + 1
    emit({"type": "turn_start", "turn_id": turn_id, "model": app.model, "persona": active.persona_id,
          "number": number, "budget_seconds": cfg.operation_timeout})
    text = screen(app, text, emit)
    if text is None:  # Refused before the model: nothing is sent, kept or saved.
        emit({"type": "done", "status": "completed", "turn_id": turn_id})
        return "blocked"
    token = CancellationToken(monotonic() + cfg.operation_timeout, stop.is_set)
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
    status = None
    stream = run_with_tools(
        session, registry, text, token,
        on_tool=lambda call, result: registry.malformed(call, result) if call.name == INVALID else None)
    try:
        for chunk in stream:
            emit({"type": "text", "delta": chunk})
        status = "completed"
    except OperationCancelled:
        status = "interrupted"
    except OperationTimedOut:
        status = "timed_out"
    except ValueError:
        emit({"type": "error", "code": "empty_input", "message": "Please type something.", "hint": None})
    except LLMError as exc:
        emit({"type": "error", **llm_failure(exc, app.model)})
    except GuardrailRefused as exc:
        stopped(emit, exc)
        status = "blocked"
    except SensaiError as exc:
        emit({"type": "error", "code": "error", "message": str(exc), "hint": None})
    finally:
        stream.close()
        registry.close()
        remove_stale_folders()  # A killed tool worker may not have removed its folder.
    settle(app, active, status == "completed", emit)  # Fact changes count only for a completed reply.
    if status == "blocked":  # The reply was stopped: the page drops it, nothing is saved.
        emit({"type": "done", "status": "completed", "turn_id": turn_id})
        return status
    if status is None:
        return None
    if status == "completed":
        websearch.sources(app, emit)
        usage = app.usage.summary()
        emit({"type": "usage", **usage})
        active.prompt_tokens = _add(active.prompt_tokens, usage["prompt_tokens"])
        active.output_tokens = _add(active.output_tokens, usage["output_tokens"])
        active.last_prompt_tokens = usage["prompt_tokens"]
        _persist(app, active, emit, stop, cfg.operation_timeout)
        active.updated_at = now()
        if active.recorder.saved:
            app.times.record(active.recorder.session_id, number, started_at, active.updated_at)
        after_turn(app, active, stop, emit)
    emit({"type": "done", "status": status, "turn_id": turn_id})
    return status
