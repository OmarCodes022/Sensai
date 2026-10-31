"""Guardrails (EV2) in the page: screen a message before the model, report a reply that was stopped."""
from sensai.core.errors import GuardrailRefused
from sensai.guardrails.rules import message_for


def screen(app, text: str, emit) -> str | None:
    """The message as the model may see it, or None when it is refused (the page shows why)."""
    decision = app.guard.inspect(text, "input")
    if not decision.allowed:
        emit({"type": "blocked", "direction": "input", "reason": decision.reason, "message": message_for(decision.reason)})
        return None
    if decision.text != text:
        emit({"type": "redacted", "parts": [{"class": c} for c in decision.reason.split(",") if c], "sent_as": decision.text})
    return decision.text


def stopped(emit, exc: GuardrailRefused) -> None:
    emit({"type": "blocked", "direction": exc.direction, "reason": exc.reason, "message": str(exc)})
