"""Wire format of the Ollama /api/chat endpoint."""
from pydantic import BaseModel

from sensai.messages import Message


class ChatRequest(BaseModel):
    model: str
    messages: list[Message]
    stream: bool = True


class ChatChunk(BaseModel):
    message: Message | None = None
    done: bool = False
    error: str | None = None
