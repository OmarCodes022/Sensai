"""The interface every model backend implements."""
from abc import ABC, abstractmethod
from collections.abc import Iterator, Sequence

from sensai.core.messages import Message
from sensai.core.cancellation import CancellationToken


def close_stream(stream, failure: BaseException | None = None):
    """Close an optional resource without replacing an active backend failure."""
    close = getattr(stream, "close", None)
    if not callable(close):
        return
    try:
        close()
    except Exception as exc:
        if failure is None or isinstance(failure, GeneratorExit):
            raise
        if hasattr(failure, "add_note"):
            failure.add_note(f"stream cleanup failed: {type(exc).__name__}")


class LLMClient(ABC):
    @abstractmethod
    def stream(self, model: str, messages: Sequence[Message],
               cancellation: CancellationToken | None = None) -> Iterator[str]:
        """Yield the reply to `messages` as text chunks. Raise LLMError on failure."""
