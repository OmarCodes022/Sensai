"""The persona catalogue as the page shows and edits it (the registry keeps only prompts).

Personas live in a JSON file (data/personas.json by default). With no file the packaged
built-ins are used, and the first edit writes data/personas.json, seeded with them.
"""
import json
import os
import re
import tempfile
from importlib.resources import files
from pathlib import Path

from sensai.chat.personas import DEFAULT_FILE, PersonaRegistry

FIELDS = ("name", "tone", "role", "response_scope")
ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,39}\Z")
MAX_TEXT = 2000

# Starter prompts shown on an empty chat, by persona id.
STARTERS = {
    "redaction": ["Write 2 caption variants for Hydra Glow Serum using only approved claims",
                  "Draft a launch post for Calm Barrier Cream", "Rewrite this caption to sound warmer"],
    "communaute": ["Suggest an unsent reply to: Does the serum work on dry skin?",
                   "Reply to a question about shipping times", "Help me answer a worried follow-up kindly"],
    "analyse": ["Summarise last week's engagement from these figures",
                "Explain the zero-reach day on 28 Sep", "What should we test next week?"],
}
# Personas whose output is a draft for the creator to review, never something sent.
DRAFT_PERSONAS = ("redaction", "communaute")


class Catalogue:
    def __init__(self, path: str | None = None):
        self.file = path or (DEFAULT_FILE if os.path.isfile(DEFAULT_FILE) else None)
        source = Path(self.file) if self.file else files("sensai.chat").joinpath("personas.json")
        self.items: list[dict] = json.loads(source.read_text(encoding="utf-8"))
        self.registry = PersonaRegistry(self.items)  # validates the catalogue

    @property
    def source(self) -> str:
        """The file in use, or "builtin"."""
        return self.file or "builtin"

    def default_id(self) -> str:
        return self.items[0]["id"].strip()

    def describe(self) -> list[dict]:
        out = []
        for item in self.items:
            entry = {key: item[key].strip() for key in ("id", *FIELDS)}
            if entry["id"] in STARTERS:
                entry["starters"] = STARTERS[entry["id"]]
            out.append(entry)
        return out

    def drafts(self) -> list[str]:
        ids = {item["id"].strip() for item in self.items}
        return [persona for persona in DRAFT_PERSONAS if persona in ids]

    # Editing: validate by building the registry from the new list, then write the file.

    @staticmethod
    def _clean(persona_id: object, data: object) -> dict:
        if not isinstance(persona_id, str) or not ID.match(persona_id):
            raise ValueError("The id uses lowercase letters, digits, dashes and underscores (at most 40).")
        if not isinstance(data, dict):
            raise ValueError("Send the persona as an object.")
        entry = {"id": persona_id}
        for field in FIELDS:
            value = data.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field} must not be empty.")
            if len(value) > MAX_TEXT:
                raise ValueError(f"{field} is longer than {MAX_TEXT} characters.")
            entry[field] = value.strip()
        return entry

    def _commit(self, items: list[dict]) -> None:
        registry = PersonaRegistry(items)  # Raises ValueError for anything the CLI would refuse too.
        target = self.file or DEFAULT_FILE
        folder = os.path.dirname(os.path.abspath(target))
        os.makedirs(folder, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=folder, prefix=".personas-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(items, f, ensure_ascii=False, indent=2)
                f.write("\n")
            os.replace(temporary, target)
        except BaseException:
            try:
                os.remove(temporary)
            except OSError:
                pass
            raise
        self.items, self.registry, self.file = items, registry, target

    def upsert(self, persona_id: object, data: object) -> str:
        """Add or replace a persona and save the catalogue. Returns "added" or "updated"."""
        entry = self._clean(persona_id, data)
        items = [dict(item) for item in self.items]
        for i, item in enumerate(items):
            if item["id"].strip() == persona_id:
                items[i] = entry
                self._commit(items)
                return "updated"
        self._commit(items + [entry])
        return "added"

    def remove(self, persona_id: object) -> None:
        items = [dict(item) for item in self.items if item["id"].strip() != persona_id]
        if len(items) == len(self.items):
            raise KeyError(persona_id)
        if not items:
            raise ValueError("Keep at least one persona.")
        self._commit(items)
