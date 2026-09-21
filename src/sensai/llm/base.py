"""The interface every model backend implements."""
from abc import ABC, abstractmethod
from collections.abc import Iterator, Sequence

from sensai.messages import Message


class LLMClient(ABC):
    @abstractmethod
    def stream(self, model: str, messages: Sequence[Message]) -> Iterator[str]:
        """Yield the reply to `messages` as text chunks. Raise LLMError on failure."""
