"""The persona catalogue as the page shows it (the registry keeps only prompts)."""
import json
from importlib.resources import files
from pathlib import Path

from sensai.chat.personas import PersonaRegistry

# Starter prompts for the packaged personas; custom catalogues have none.
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
        source = Path(path) if path is not None else files("sensai.chat").joinpath("personas.json")
        self.items: list[dict] = json.loads(source.read_text(encoding="utf-8"))
        self.registry = PersonaRegistry(self.items)  # validates the catalogue
        self.source = "file" if path is not None else "builtin"

    def describe(self) -> list[dict]:
        out = []
        for item in self.items:
            entry = {key: item[key].strip() for key in ("id", "name", "tone", "role", "response_scope")}
            if self.source == "builtin" and entry["id"] in STARTERS:
                entry["starters"] = STARTERS[entry["id"]]
            out.append(entry)
        return out

    def drafts(self) -> list[str]:
        ids = {item["id"].strip() for item in self.items}
        return [persona for persona in DRAFT_PERSONAS if persona in ids] if self.source == "builtin" else []
