"""Wire format of the Ollama /api/chat endpoint."""
from dataclasses import dataclass
from enum import Enum

from pydantic import BaseModel, Field, StrictInt

from sensai.messages import Message


class ChatRequest(BaseModel):
    model: str
    messages: list[Message]
    stream: bool = True


class ChatChunk(BaseModel):
    message: Message | None = None
    done: bool = False
    error: str | None = None
    prompt_eval_count: StrictInt | None = Field(default=None, ge=0)
    eval_count: StrictInt | None = Field(default=None, ge=0)
    total_duration: StrictInt | None = Field(default=None, ge=0)


class UsageError(str, Enum):
    CONNECTION = "connection"
    TIMEOUT = "timeout"
    MODEL_NOT_FOUND = "model_not_found"
    HTTP = "http"
    REMOTE = "remote"
    INVALID_RESPONSE = "invalid_response"
    INCOMPLETE_STREAM = "incomplete_stream"
    TRANSPORT = "transport"
    CANCELLED = "cancelled"
    TOOL_FAILURE = "tool_failure"


@dataclass(frozen=True)
class OllamaUsage:
    """One attempted request; absent counts mean Ollama did not report them."""

    prompt_tokens: int | None
    output_tokens: int | None
    latency_ms: float
    error: UsageError | None = None
    server_duration_ms: float | None = None
