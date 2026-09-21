"""Exception hierarchy. Catch SensaiError to handle anything raised by the project."""


class SensaiError(Exception):
    pass


class LLMError(SensaiError):
    """Any failure talking to a language model backend."""


class ModelNotFoundError(LLMError):
    pass


class LLMConnectionError(LLMError):
    pass
