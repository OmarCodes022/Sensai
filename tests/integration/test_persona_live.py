"""Opt-in persona switch against a real local Ollama. Skipped when the server or model is missing.

Model comes from SENSAI_TEST_MODEL (see .env.example). Checks mechanics only:
streaming, retained context and history shape, not language or answer quality.
"""

import pytest
import requests

from sensai.chat.personas import PersonaRegistry
from sensai.chat.prompts import load_system_prompt
from sensai.chat.session import ChatSession
from sensai.settings import Settings
from sensai.llm import create_client

S = Settings()
SHARED = load_system_prompt()


def _model_available():
    try:
        tags = requests.get(f"{S.host}/api/tags", timeout=2).json()
    except (requests.RequestException, ValueError):
        return False
    return any(m["name"].startswith(S.test_model) for m in tags.get("models", []))


pytestmark = pytest.mark.skipif(
    not _model_available(), reason=f"Ollama or {S.test_model} unavailable"
)


def test_switched_persona_streams_and_keeps_earlier_context():
    registry = PersonaRegistry.from_file()
    analyse = f"{SHARED}\n\n{registry.get('analyse').system_prompt}"
    session = ChatSession(create_client(S), S.test_model,
                          f"{SHARED}\n\n{registry.get('redaction').system_prompt}")
    "".join(session.send("The fictional campaign code is AZUR729. Acknowledge briefly."))
    session.set_system_prompt(analyse)
    chunks = list(session.send(
        "What is the fictional campaign code I gave you? Repeat it exactly, in one sentence."))
    assert len(chunks) > 1
    answer = "".join(chunks)
    assert answer.strip()
    assert "azur729" in "".join(c for c in answer if c.isalnum()).casefold()
    assert [m.role for m in session.messages] == [
        "system", "user", "assistant", "user", "assistant",
    ]
    assert session.messages[0].content == analyse
