"""ask_user (X4) in the page: the turn shows a form and waits here until POST /api/questions/{id} answers."""
from time import monotonic

from sensai.chat.questions import SKIPPED, answers_text, check_answers, parse
from sensai.core.ports import ToolResult


class WebForm:
    """The ask_user handler for one turn: announce the form, wait for the page (or Stop), return the answers."""

    def __init__(self, pending, emit, stop, turn_id: str, approval):
        self._pending = pending  # an Approvals table: id -> (Event, [answer])
        self._emit = emit
        self._stop = stop
        self._turn_id = turn_id
        self._approval = approval  # Its `waited` excludes the time spent answering from the tool's duration.
        self._count = 0

    def __call__(self, arguments, cancellation=None) -> ToolResult:
        try:
            questions = parse(arguments)
        except ValueError as exc:
            return ToolResult("", str(exc))
        self._count += 1
        form_id = f"{self._turn_id}-q{self._count}"
        done, answer = self._pending.open(form_id)
        self._emit({"type": "question", "id": form_id, "call_id": self._approval.call_id,
                    "questions": [{"type": q.kind, "text": q.text, "options": list(q.options)} for q in questions]})
        started, given = monotonic(), None
        try:
            while not self._stop.is_set():
                if done.wait(0.1):
                    given = answer[0]
                    break
        finally:
            self._pending.close(form_id)
            self._approval.waited += monotonic() - started
        try:
            given = check_answers(questions, given) if isinstance(given, list) else None
        except ValueError:  # Wrong number of answers: treated as a skip, never guessed.
            given = None
        skipped = given is None
        self._emit({"type": "question_result", "id": form_id, "skipped": skipped})
        return ToolResult(SKIPPED if skipped else answers_text(questions, given))


def answer(app, form_id: str, body: dict) -> dict:
    """Store the page's answers (checked by the form's own rules later) or a skip."""
    from sensai_web.errors import ApiError
    if body.get("skipped") is True:
        value = None
    else:
        answers = body.get("answers")
        if not isinstance(answers, list) or not all(isinstance(a, str) and a.strip() for a in answers):
            raise ApiError(400, "bad_answer", "Answer every question, or skip the form.")
        value = [a.strip() for a in answers]
    if not app.questions.decide(form_id, value):
        raise ApiError(404, "not_found", "No question is waiting for this answer.")
    return {"ok": True}
