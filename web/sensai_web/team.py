"""/team over HTTP (A2): the researcher, writer and reviewer steps as stream events; only the brief and the
final draft join the conversation."""
from time import monotonic
from uuid import uuid4

from sensai.chat.agents import brand_facts, team
from sensai.chat.saved_sessions import user_messages
from sensai.core.cancellation import CancellationToken, OperationCancelled, OperationTimedOut
from sensai.core.errors import LLMError, SensaiError
from sensai.core.messages import Message
from sensai.guardrails.rules import message_for
from sensai_web.app import ActiveSession, WebApp, now
from sensai_web.errors import llm_failure
from sensai_web.guard import screen
from sensai_web.think import _writer
from sensai_web.turn import Emit, _add, _persist


def run_team(app: WebApp, active: ActiveSession, stop, brief: str, emit: Emit):
    cfg, session = app.cfg, active.session
    started_at, turn_id = now(), f"t{uuid4().hex[:8]}"
    number = len(user_messages(session.messages)) + 1
    emit({"type": "turn_start", "turn_id": turn_id, "model": app.model, "persona": active.persona_id,
          "number": number, "budget_seconds": cfg.operation_timeout, "think": True})
    brief = screen(app, brief, emit)
    if brief is None:
        emit({"type": "done", "status": "completed", "turn_id": turn_id})
        return "blocked"
    facts = "\n".join(part for part in (brand_facts(app.brand_file), app.memory.block()) if part)
    client = getattr(app.chat_client, "client", app.chat_client)  # Drafts in between are not checked, the final one is.
    write, status, result = _writer(emit), None, None
    stream = team(brief, client, app.checker, app.model, facts,
                  lambda: CancellationToken(monotonic() + cfg.operation_timeout, stop.is_set))
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
        emit({"type": "error", **llm_failure(exc, app.model)})
    except SensaiError as exc:
        emit({"type": "error", "code": "error", "message": str(exc), "hint": None})
    finally:
        stream.close()
    if status == "completed" and not (decision := app.guard.inspect(result.draft, "output")).allowed:
        emit({"type": "blocked", "direction": "output", "reason": decision.reason, "message": message_for(decision.reason)})
        status = "blocked"
    if status == "blocked":  # The final draft was stopped: nothing joins the conversation.
        emit({"type": "done", "status": "completed", "turn_id": turn_id})
        return status
    if status is None:
        return None
    if status == "completed":
        emit({"type": "text", "delta": f"\n\n**Final draft{f' ({result.revisions} revision(s))' if result.revisions else ''}**\n\n{result.answer}"})
        session.messages += [Message(role="user", content=f"/team {brief}"), Message(role="assistant", content=result.answer)]
        usage = app.usage.summary()
        emit({"type": "usage", **usage})
        active.prompt_tokens = _add(active.prompt_tokens, usage["prompt_tokens"])
        active.output_tokens = _add(active.output_tokens, usage["output_tokens"])
        _persist(app, active, emit, stop, cfg.operation_timeout)
        active.updated_at = now()
        if active.recorder.saved:
            app.times.record(active.recorder.session_id, number, started_at, active.updated_at, usage)
    emit({"type": "done", "status": status, "turn_id": turn_id})
    return status
