"""One chat turn as stream events: text, tool calls, approvals, usage, saving, done."""
from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic
from uuid import uuid4

from sensai.chat import saved_sessions
from sensai.chat.reasoning import Section, think
from sensai.chat.saved_sessions import user_messages
from sensai.core.cancellation import CancellationToken, OperationCancelled, OperationTimedOut
from sensai.core.errors import LLMError, SensaiError
from sensai.core.messages import Message
from sensai.sandbox import remove_stale_folders
from sensai.tools import run_with_tools
from sensai_web.app import ActiveSession, WebApp, now
from sensai_web.approvals import WebApproval
from sensai_web.errors import llm_failure
from sensai_web.tools import INVALID, ObservedRegistry

Emit = Callable[[dict], None]


@dataclass
class _Turn:
    turn_id: str
    number: int
    started_at: str


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
        return saved_sessions.generate_title(app.title_client, app.cfg.model, first_user, first_answer, token)

    recorder.titler = titler
    recorder.after_turn(active.session)
    if recorder.saved and not saved_before:
        active.created_at = now()
        emit({"type": "saved", "session_id": recorder.session_id})
    if recorder.title and recorder.title != title_before:
        emit({"type": "title", "title": recorder.title})


def _begin(app: WebApp, active: ActiveSession, emit: Emit) -> _Turn:
    turn = _Turn(f"t{uuid4().hex[:8]}", len(user_messages(active.session.messages)) + 1, now())
    emit({"type": "turn_start", "turn_id": turn.turn_id, "model": app.cfg.model, "persona": active.persona_id,
          "number": turn.number, "budget_seconds": app.cfg.operation_timeout})
    return turn


def _registry(app: WebApp, active: ActiveSession, stop, emit: Emit, turn: _Turn) -> ObservedRegistry:
    """Bring the prompt up to date (with its notices), then the turn's observed tools."""
    for notice in app.refresh_prompt(active):
        emit({"type": "warning", "code": "documents", "message": notice})
    approval = WebApproval(app.approvals, emit, stop, turn.turn_id)
    return ObservedRegistry(approval, emit, app.data.path, app.meta_dir, app.docs)


def _play(app: WebApp, registry: ObservedRegistry, emit: Emit, body: Callable[[], None]) -> str | None:
    """Run the turn's body; return its status, or None after an `error` event."""
    try:
        body()
        return "completed"
    except OperationCancelled:
        return "interrupted"
    except OperationTimedOut:
        return "timed_out"
    except ValueError:
        emit({"type": "error", "code": "empty_input", "message": "Please type something.", "hint": None})
    except LLMError as exc:
        emit({"type": "error", **llm_failure(exc, app.cfg.model)})
    except SensaiError as exc:
        emit({"type": "error", "code": "error", "message": str(exc), "hint": None})
    finally:
        registry.close()
        remove_stale_folders()  # A killed tool worker may not have removed its folder.
    return None


def _finish(app: WebApp, active: ActiveSession, stop, emit: Emit, turn: _Turn, status: str | None) -> None:
    """Usage, saving and `done` for a turn that did not fail; nothing at all after an error."""
    if status is None:
        return
    if status == "completed":
        usage = app.usage.summary()
        emit({"type": "usage", **usage})
        active.prompt_tokens = _add(active.prompt_tokens, usage["prompt_tokens"])
        active.output_tokens = _add(active.output_tokens, usage["output_tokens"])
        active.last_prompt_tokens = usage["prompt_tokens"]
        _persist(app, active, emit, stop, app.cfg.operation_timeout)
        active.updated_at = now()
        if active.recorder.saved:
            app.times.record(active.recorder.session_id, turn.number, turn.started_at, active.updated_at)
    emit({"type": "done", "status": status, "turn_id": turn.turn_id})


def run_turn(app: WebApp, active: ActiveSession, stop, text: str, emit: Emit) -> None:
    """Answer `text` on the active session. Ends with `done`, or with `error` when the turn failed."""
    turn = _begin(app, active, emit)
    token = CancellationToken(monotonic() + app.cfg.operation_timeout, stop.is_set)
    registry = _registry(app, active, stop, emit, turn)

    def body():
        stream = run_with_tools(
            active.session, registry, text, token,
            on_tool=lambda call, result: registry.malformed(call, result) if call.name == INVALID else None)
        try:
            for chunk in stream:
                emit({"type": "text", "delta": chunk})
        finally:
            stream.close()

    _finish(app, active, stop, emit, turn, _play(app, registry, emit, body))


def run_think(app: WebApp, active: ActiveSession, stop, text: str, emit: Emit) -> None:
    """/think on the active session: every step streams; only `text` and the final answer are kept."""
    turn = _begin(app, active, emit)
    registry = _registry(app, active, stop, emit, turn)
    rounds: list[Section | str] = []

    def new_token() -> CancellationToken:
        # Each step gets the whole budget (as in the terminal); Stop cancels every one.
        return CancellationToken(monotonic() + app.cfg.operation_timeout, stop.is_set)

    def show(item: Section | str) -> None:
        if isinstance(item, Section):
            emit({"type": "think_section", "title": item.title})
        elif item:
            emit({"type": "text", "delta": item})

    def on_tool(call, result) -> None:
        # The round's Act/Observe items wait here, so they always follow its tool_call/tool_result.
        if call.name == INVALID:
            registry.malformed(call, result)
        for item in rounds:
            show(item)
        rounds.clear()

    def body():
        stream = think(active.session, registry, text, app.checker, new_token=new_token,
                       on_tool=on_tool, emit=rounds.append)
        try:
            while True:
                try:
                    show(next(stream))
                except StopIteration as stop_iteration:
                    result = stop_iteration.value
                    break
        finally:
            stream.close()
        emit({"type": "think_done", "answer": result.answer, "rounds": result.rounds,
              "tool_calls": result.tool_calls, "unresolved": list(result.unresolved), "checked": result.checked})
        active.session.messages.append(Message(role="user", content=text))
        active.session.messages.append(Message(role="assistant", content=result.answer))

    _finish(app, active, stop, emit, turn, _play(app, registry, emit, body))
