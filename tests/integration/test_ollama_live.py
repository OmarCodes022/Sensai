"""Tests against a real local Ollama. Skipped when the server or model is missing.

Model comes from SENSAI_TEST_MODEL (see .env.example).
"""
import pytest
import requests

from sensai.errors import LLMConnectionError, ModelNotFoundError
from sensai.llm.ollama import OllamaClient
from sensai.messages import Message
from sensai.session import ChatSession
from sensai.settings import Settings

S = Settings()
HI = [Message(role="user", content="hi")]


def _model_available():
    try:
        tags = requests.get(f"{S.host}/api/tags", timeout=2).json()
    except (requests.RequestException, ValueError):
        return False
    return any(m["name"].startswith(S.test_model) for m in tags.get("models", []))


pytestmark = pytest.mark.skipif(
    not _model_available(), reason=f"Ollama or {S.test_model} unavailable"
)


def client():
    return OllamaClient(S.host, S.timeout)


def test_stream_is_progressive():
    msgs = [Message(role="user", content="Count from 1 to 10.")]
    chunks = list(client().stream(S.test_model, msgs))
    assert len(chunks) > 1
    assert "".join(chunks).strip()


def test_history_is_used():
    s = ChatSession(client(), S.test_model, "Answer briefly.")
    "".join(s.send("My secret word is PINEAPPLE. Remember it."))
    assert "pineapple" in "".join(s.send("What is my secret word?")).lower()


def test_unknown_model():
    with pytest.raises(ModelNotFoundError):
        list(client().stream("no-such-model-xyz", HI))


def test_connection_refused():
    with pytest.raises(LLMConnectionError):
        list(OllamaClient("http://127.0.0.1:1").stream(S.test_model, HI))
