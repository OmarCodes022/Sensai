"""/edit N in the page: continue from message N as a new saved session, the original left unchanged."""
from sensai.chat import saved_sessions
from sensai.chat.saved_sessions import branch_title, display_title, messages_before_user, user_messages
from sensai_web.app import ActiveSession, WebApp
from sensai_web.errors import ApiError
from sensai_web.turn import Emit, run_turn


def check(app: WebApp, number: object, text: object) -> tuple[int, str]:
    """The message number and new text, or a 400 the page shows."""
    if not isinstance(text, str) or not text.strip():
        raise ApiError(400, "empty_input", "Write the new text for this message.")
    with app.mutex:
        count = len(user_messages(app.active.session.messages))
    if isinstance(number, bool) or not isinstance(number, int) or not 1 <= number <= count:
        raise ApiError(400, "bad_message", f"There is no message {number}." if count else "There are no messages to edit yet.")
    return number, text.strip()


def fork(app: WebApp, active: ActiveSession, number: int) -> ActiveSession:
    """A new unsaved session holding the messages before `number`, titled after the original plus "(branch)"."""
    kept = [m for m in messages_before_user(active.session.messages, number) if m.role != "system"]
    with app.creator_storage() as creator:
        known = {s.id for s in creator.sessions.list()}
    branch = app._active(saved_sessions.new_session_id(known.__contains__), active.persona_id, kept)
    original = [m for m in active.session.messages if m.role != "system"]
    branch.recorder.title = branch_title(active.recorder.title or display_title(None, original))
    return branch


def run_edit(app: WebApp, active: ActiveSession, stop, number: int, text: str, emit: Emit) -> None:
    """Answer on the branch; only a completed reply makes it the open conversation."""
    branch = fork(app, active, number)
    emit({"type": "branch", "session_id": branch.recorder.session_id, "from": active.recorder.session_id,
          "number": number})
    if run_turn(app, branch, stop, text, emit) == "completed":
        app.times.copy(active.recorder.session_id, branch.recorder.session_id, number - 1)
        with app.mutex:
            app.active = branch
