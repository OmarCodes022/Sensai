"""Conversation state, independent of backend and UI."""
from collections.abc import Iterator

from sensai.errors import LLMError
from sensai.llm.base import LLMClient
from sensai.messages import Message


class ChatSession:
    def __init__(self, client: LLMClient, model: str, system_prompt: str):
        self.client = client
        self.model = model
        self.messages: list[Message] = [Message(role="system", content=system_prompt)]

    def send(self, text: str) -> Iterator[str]:
        if not text.strip():
            raise ValueError("empty input")
        self.messages.append(Message(role="user", content=text))
        reply: list[str] = []
        try:
            for chunk in self.client.stream(self.model, list(self.messages)):
                reply.append(chunk)
                yield chunk
        except LLMError:
            self.messages.pop()
            raise
        self.messages.append(Message(role="assistant", content="".join(reply)))
