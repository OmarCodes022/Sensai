"""Exception hierarchy. Catch SensaiError to handle anything raised by the project."""


class SensaiError(Exception):
    pass


class LLMError(SensaiError):
    """Any failure talking to a language model backend."""


class ModelNotFoundError(LLMError):
    pass


class LLMConnectionError(LLMError):
    pass


class GuardrailRefused(SensaiError):
    """A message or a reply was refused by the content and privacy guardrails (EV2)."""

    def __init__(self, reason: str, message: str, direction: str):
        super().__init__(message)
        self.reason = reason
        self.direction = direction
