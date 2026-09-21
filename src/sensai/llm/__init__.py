from sensai.llm.base import LLMClient
from sensai.llm.ollama import OllamaClient
from sensai.settings import Settings


def create_client(settings: Settings) -> LLMClient:
    """Single place to pick a backend as more are added."""
    return OllamaClient(settings.host, settings.timeout)


__all__ = ["LLMClient", "OllamaClient", "create_client"]
