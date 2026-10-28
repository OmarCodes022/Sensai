"""API errors and the stable codes the page shows for model failures."""
from sensai.core.errors import LLMConnectionError, LLMError, ModelNotFoundError


class ApiError(Exception):
    """An error answered as {"error": {code, message, hint}} with an HTTP status."""

    def __init__(self, status: int, code: str, message: str, hint: str | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.hint = hint

    def payload(self) -> dict:
        return {"code": self.code, "message": self.message, "hint": self.hint}


def llm_failure(exc: LLMError, model: str | None) -> dict:
    """Map a model failure to {code, message, hint}; the message is already user safe."""
    text = str(exc)
    if isinstance(exc, ModelNotFoundError):
        return {"code": "model_not_found", "message": text, "hint": f"ollama pull {model}"}
    if isinstance(exc, LLMConnectionError):
        return {"code": "connection", "message": text, "hint": "ollama serve"}
    if "timed out" in text:
        return {"code": "timeout", "message": text, "hint": None}
    if text.startswith("invalid response"):
        return {"code": "invalid_response", "message": text, "hint": None}
    return {"code": "llm_error", "message": text, "hint": None}
