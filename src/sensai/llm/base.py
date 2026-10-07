"""The interface every model backend implements."""
from abc import ABC, abstractmethod
from collections.abc import Iterator, Sequence

from sensai.core.messages import Message
from sensai.core.cancellation import CancellationToken


class LLMClient(ABC):
    @abstractmethod
    def stream(self, model: str, messages: Sequence[Message],
               cancellation: CancellationToken | None = None) -> Iterator[str]:
        """Yield the reply to `messages` as text chunks. Raise LLMError on failure."""
