"""Conversation state, independent of backend and UI."""
from collections.abc import Iterator

from sensai.core.cancellation import CancellationToken
from sensai.core.errors import LLMError
from sensai.llm.client import LLMClient, close_stream
from sensai.core.messages import Message


class ChatSession:
    def __init__(self, client: LLMClient, model: str, system_prompt: str):
        self.client = client
        self.model = model
        self.messages: list[Message] = [Message(role="system", content=system_prompt)]
        self._system_prompt_changed = False

    def set_system_prompt(self, prompt: str) -> None:
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("system prompt must be a nonempty string")
        self.messages[0] = Message(role="system", content=prompt)
        self._system_prompt_changed = True

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
            messages = list(self.messages)
            if self._system_prompt_changed:
                # Older assistant introductions must not undo the active role.
                messages.insert(-1, self.messages[0])
            if cancellation is None:
                stream = self.client.stream(self.model, messages)
            else:
                stream = self.client.stream(self.model, messages, cancellation=cancellation)
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
            answer = "".join(reply)
            if not answer.strip():
                raise LLMError("model returned no visible answer")
            self.messages.append(Message(role="assistant", content=answer))
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
