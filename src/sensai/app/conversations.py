"""Persistent CLI conversations: session IDs, creator profile, titles and saving."""

import json
import secrets
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from sensai.core.cancellation import CancellationToken
from sensai.core.contracts import PortError, SessionSnapshot
from sensai.core.errors import SensaiError
from sensai.core.messages import Message
from sensai.llm.base import LLMClient, close_stream

ID_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
PROFILE_HEADER = "Profil de la créatrice (instructions personnalisées) :"
TITLE_PROMPT = (
    "Donne un titre court (3 à 6 mots) à cette conversation, dans la langue de la conversation. "
    "Réponds uniquement par le titre, sur une seule ligne, sans guillemets."
)
QUOTES = "\"'«»“”‘’`"
TITLE_TIMEOUT = 15.0


def new_session_id(exists: Callable[[str], bool]) -> str:
    while True:
        session_id = "".join(secrets.choice(ID_ALPHABET) for _ in range(6))
        if not exists(session_id):
            return session_id


def load_profile_file(path: str | Path) -> dict[str, str]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("profile file must contain a JSON object")
    preferences: dict[str, str] = {}
    for key, value in data.items():
        if not isinstance(value, str) or not key.strip() or not value.strip():
            raise ValueError(f"profile entry {key!r} must map a nonempty key to a nonempty string")
        if key.strip() in preferences:
            raise ValueError(f"duplicate profile key: {key.strip()}")
        preferences[key.strip()] = value.strip()
    return preferences


def profile_block(preferences: Mapping[str, str]) -> str:
    lines = [f"- {key} : {text}" for key, text in preferences.items() if key.strip() and text.strip()]
    return "\n".join([PROFILE_HEADER, *lines]) if lines else ""


def fallback_title(text: str) -> str:
    lines = text.strip().splitlines()
    title = " ".join(lines[0].split()) if lines else ""
    return title if len(title) <= 40 else title[:39].rstrip() + "…"


def generate_title(client: LLMClient, model: str, first_user: str, first_answer: str,
                   cancellation: CancellationToken | None = None) -> str | None:
    """Ask for a short title in a separate request; None means use the fallback."""
    messages = [
        Message(role="system", content=TITLE_PROMPT),
        Message(role="user", content=f"Message : {first_user[:2000]}\n\nRéponse : {first_answer[:2000]}"),
    ]
    stream = None
    try:
        stream = client.stream(model, messages, cancellation=cancellation)
        chunks = []
        for chunk in stream:
            if cancellation is not None:
                cancellation.raise_if_cancelled()
            chunks.append(chunk)
        if cancellation is not None:
            cancellation.raise_if_cancelled()
    except (SensaiError, KeyboardInterrupt):
        return None
    finally:
        try:
            close_stream(stream)
        except SensaiError:
            pass
    title = "".join(chunks).strip().strip(QUOTES).strip()
    if len(title.splitlines()) != 1:
        return None
    title = " ".join(title.split())  # NBSP / narrow NBSP of French typography → spaces
    if not title.isprintable() or len(title) > 60:
        return None
    return title


def first_exchange(messages: Sequence[Message]) -> tuple[str, str]:
    user = next((m.content for m in messages if m.role == "user"), "")
    answer = next((m.content for m in messages if m.role == "assistant"), "")
    return user, answer


def display_title(title: str | None, messages: Sequence[Message]) -> str:
    return title or fallback_title(first_exchange(messages)[0]) or "(sans titre)"


class SessionRecorder:
    """Save each completed turn; storage failures are reported and never stop the chat."""

    def __init__(self, store, session_id: str, persona_id: str | None = None, *,
                 title: str | None = None, saved: bool = False,
                 titler: Callable[[str, str], str | None] | None = None,
                 messages: Sequence[Message] = (), write=print):
        self.store = store
        self.session_id = session_id
        self.persona_id = persona_id
        self.title = title
        self.titled = title is not None
        self.saved = saved
        self.titler = titler
        self.messages = tuple(messages)
        self.write = write

    def after_turn(self, session) -> None:
        self.messages = tuple(m for m in session.messages if m.role != "system")
        if not self._save() or self.titled:
            return
        if self.title is None:  # computed once; a failed write is retried, never the request
            first_user, first_answer = first_exchange(self.messages)
            self.title = (self.titler(first_user, first_answer) if self.titler else None) \
                or fallback_title(first_user)
        if not self.title:
            return
        try:
            self.store.set_title(self.session_id, self.title)
        except (PortError, sqlite3.Error) as e:
            self.write(f"error: session title not saved: {e}")
        except KeyboardInterrupt:
            self.write("error: session title not saved: interrupted")
        else:
            self.titled = True

    def persona_changed(self, persona_id: str) -> None:
        self.persona_id = persona_id
        if self.saved:
            self._save()

    def _save(self) -> bool:
        try:
            self.store.save(SessionSnapshot(self.session_id, self.messages, self.persona_id))
        except (PortError, sqlite3.Error) as e:
            self.write(f"error: session not saved: {e}")
            return False
        except KeyboardInterrupt:
            self.write("error: session not saved: interrupted")
            return False
        self.saved = True
        return True
