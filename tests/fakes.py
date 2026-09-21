from sensai.llm.base import LLMClient


class FakeClient(LLMClient):
    """Replays scripted replies (each a list of chunks or an exception) and records calls."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def stream(self, model, messages):
        self.calls.append([m.content for m in messages])
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        yield from reply
