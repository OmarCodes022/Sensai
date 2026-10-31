"""GuardedClient: checks a reply line by line before any of it is shown, so it still streams."""
from collections.abc import Iterator, Sequence

from sensai.core.errors import GuardrailRefused
from sensai.core.messages import Message
from sensai.guardrails.rules import Guardrail, message_for
from sensai.llm.client import LLMClient, close_stream


class GuardedClient(LLMClient):
    def __init__(self, client: LLMClient, guard: Guardrail):
        self.client = client
        self.guard = guard

    def __getattr__(self, name):  # Usage hooks and the like belong to the wrapped client.
        return getattr(self.client, name)

    def _check(self, line: str) -> str:
        decision = self.guard.inspect(line, "output")
        if not decision.allowed:
            raise GuardrailRefused(decision.reason, message_for(decision.reason), "output")
        return decision.text

    def stream(self, model: str, messages: Sequence[Message], cancellation=None) -> Iterator[str]:
        source = self.client.stream(model, messages, cancellation)
        pending = ""
        try:
            for chunk in source:
                pending += chunk
                *lines, pending = pending.split("\n")
                for line in lines:
                    yield self._check(line) + "\n"
            if pending:
                yield self._check(pending)
        finally:
            close_stream(source)
