"""ask_user (X4): when a detail is missing, the model asks through a short form instead of guessing."""
from dataclasses import dataclass

from sensai.cli.approval import sanitize
from sensai.core.ports import ToolDefinition, ToolResult

MAX_QUESTIONS = 4
MAX_OPTIONS = 8
SKIPPED = "The user skipped the question. Continue without it, or say what is missing."
ASK_USER = ToolDefinition(
    "ask_user",
    "Ask the creator one to four short questions when a detail you need is missing (for example which product). "
    "Use type choice with options when the answer is one of a few, otherwise type text.",
    {"type": "object", "required": ["questions"], "properties": {"questions": {
        "type": "array", "items": {"type": "object", "required": ["type", "text"], "properties": {
            "type": {"type": "string", "enum": ["choice", "text"]},
            "text": {"type": "string"},
            "options": {"type": "array", "items": {"type": "string"}}}}}}},
)


@dataclass(frozen=True)
class Question:
    kind: str
    text: str
    options: tuple[str, ...] = ()


def parse(arguments) -> list[Question]:
    """The questions, checked; ValueError with a message the model can read."""
    items = arguments.get("questions") if isinstance(arguments, dict) else None
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_QUESTIONS:
        raise ValueError(f"questions must be a list of 1 to {MAX_QUESTIONS} questions")
    out = []
    for item in items:
        if not isinstance(item, dict) or item.get("type") not in ("choice", "text"):
            raise ValueError("each question needs type choice or text")
        text = item.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("each question needs a text")
        options = item.get("options") or []
        if item["type"] == "choice":
            if not isinstance(options, list) or not 2 <= len(options) <= MAX_OPTIONS or \
                    not all(isinstance(o, str) and o.strip() for o in options):
                raise ValueError(f"a choice question needs 2 to {MAX_OPTIONS} options")
            options = tuple(dict.fromkeys(o.strip() for o in options))
        out.append(Question(item["type"], text.strip(), tuple(options) if item["type"] == "choice" else ()))
    return out


def answers_text(questions: list[Question], answers: list[str]) -> str:
    return "\n".join(f"{q.text} -> {a}" for q, a in zip(questions, answers))


def check_answers(questions: list[Question], answers) -> list[str]:
    """The answers given in the page, checked: one non-empty text per question."""
    if not isinstance(answers, list) or len(answers) != len(questions) or \
            not all(isinstance(a, str) and a.strip() for a in answers):
        raise ValueError("answer every question")
    return [a.strip() for a in answers]


class TerminalForm:
    """ask_user in the terminal: numbered choices with an Other entry, or free text; Ctrl+C skips."""

    def __init__(self, read, write=print):
        self._read = read
        self._write = write

    def _ask(self, question: Question) -> str:
        self._write(f"  {sanitize(question.text, keep='')}")
        if question.kind == "text":
            while not (answer := self._read("  > ").strip()):
                self._write("  Please type an answer, or press Ctrl+C to skip.")
            return answer
        choices = [*question.options, "Other (type it)"]
        self._write("    " + "   ".join(f"{n}) {sanitize(c, keep='')}" for n, c in enumerate(choices, 1)))
        while True:
            answer = self._read(f"  Choice [1-{len(choices)}]: ").strip()
            if answer.isdigit() and 1 <= int(answer) <= len(choices):
                if int(answer) <= len(question.options):
                    return question.options[int(answer) - 1]
                while not (other := self._read("  > ").strip()):
                    self._write("  Please type an answer.")
                return other
            self._write(f"  Please enter a number from 1 to {len(choices)}.")

    def __call__(self, arguments, cancellation=None) -> ToolResult:
        try:
            questions = parse(arguments)
        except ValueError as exc:
            return ToolResult("", str(exc))
        self._write("")
        self._write("Sensai needs one detail:" if len(questions) == 1 else f"Sensai needs {len(questions)} details:")
        try:
            answers = [self._ask(q) for q in questions]
        except (KeyboardInterrupt, EOFError):
            self._write("  Skipped.")
            return ToolResult(SKIPPED)
        return ToolResult(answers_text(questions, answers))
