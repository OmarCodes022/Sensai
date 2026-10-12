"""Conversation state, independent of backend and UI."""
from collections.abc import Iterator

from sensai.core.cancellation import CancellationToken
from sensai.llm.base import LLMClient, close_stream
from sensai.core.messages import Message


class ChatSession:
    def __init__(self, client: LLMClient, model: str, system_prompt: str):
        self.client = client
        self.model = model
        self.messages: list[Message] = [Message(role="system", content=system_prompt)]

    def send(self, text: str, cancellation: CancellationToken | None = None) -> Iterator[str]:
        if not text.strip():
            raise ValueError("empty input")
        if cancellation is not None:
            cancellation.raise_if_cancelled()
        count = len(self.messages)
        self.messages.append(Message(role="user", content=text))
        reply: list[str] = []
        stream = None
        completed = False
        failure = None
        try:
            if cancellation is None:
                stream = self.client.stream(self.model, list(self.messages))
            else:
                stream = self.client.stream(self.model, list(self.messages), cancellation=cancellation)
            for chunk in stream:
                if cancellation is not None:
                    cancellation.raise_if_cancelled()
                reply.append(chunk)
                yield chunk
            finished_stream = stream
            stream = None
            close_stream(finished_stream)
            if cancellation is not None:
                cancellation.raise_if_cancelled()
            self.messages.append(Message(role="assistant", content="".join(reply)))
            completed = True
        except BaseException as exc:
            failure = exc
            raise
        finally:
            try:
                close_stream(stream, failure)
            finally:
                if not completed:
                    del self.messages[count:]
