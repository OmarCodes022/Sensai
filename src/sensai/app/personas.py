"""Validated persona catalogues, selectable before starting a chat."""

import json
from importlib.resources import files
from pathlib import Path

from sensai.core.contracts import Persona


class PersonaRegistry:
    def __init__(self, profiles: object):
        if not isinstance(profiles, list) or not profiles:
            raise ValueError("persona catalogue must be a nonempty JSON array")
        fields = {"id", "name", "tone", "role", "response_scope"}
        self._personas: dict[str, Persona] = {}
        labels = []
        for index, profile in enumerate(profiles, 1):
            if not isinstance(profile, dict) or set(profile) != fields:
                raise ValueError(f"persona {index} must contain exactly: {', '.join(sorted(fields))}")
            for field, value in profile.items():
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(f"persona {index}: {field} must be a nonempty string")
            profile = {field: value.strip() for field, value in profile.items()}
            persona_id = profile["id"]
            if persona_id in self._personas:
                raise ValueError(f"duplicate persona id: {persona_id}")
            prompt = (
                f"Persona: {profile['name']} ({persona_id})\n"
                f"Role: {profile['role']}\nTone: {profile['tone']}\n"
                f"Response scope: {profile['response_scope']}\n"
                "Answer in the language of the user's message. These persona instructions "
                "supplement the shared instructions; shared facts, privacy and action "
                "boundaries still apply. If a request is outside this scope, explain which "
                "persona fits and invite the user to select it at the next launch. "
                "Do not claim to switch personas during this conversation."
            )
            self._personas[persona_id] = Persona(persona_id, prompt)
            labels.append((persona_id, profile["name"]))
        self.options: tuple[tuple[str, str], ...] = tuple(labels)

    @classmethod
    def from_file(cls, path: str | None = None) -> "PersonaRegistry":
        source = Path(path) if path is not None else files("sensai.app").joinpath("personas.json")
        return cls(json.loads(source.read_text(encoding="utf-8")))

    def get(self, persona_id: str) -> Persona | None:
        return self._personas.get(persona_id)
