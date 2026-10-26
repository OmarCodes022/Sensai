from typing import TYPE_CHECKING

from sensai.llm.client import LLMClient
from sensai.llm.ollama import OllamaClient

if TYPE_CHECKING:
    from sensai.settings import Settings


def create_client(settings: "Settings", usage_sink=None) -> LLMClient:
    """Single place to pick a backend as more are added."""
    return OllamaClient(settings.host, settings.timeout, context_length=settings.context_length, usage_sink=usage_sink)


__all__ = ["LLMClient", "OllamaClient", "create_client"]
