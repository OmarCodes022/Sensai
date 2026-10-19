"""Validated persona catalogues, selectable at startup or between turns."""

import json
from importlib.resources import files
from pathlib import Path

from sensai.core.ports import Persona


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
                f"Persona active sélectionnée par l'application : {profile['name']} ({persona_id}). "
                "Les anciennes présentations de l'assistant dans l'historique décrivent les "
                "rôles précédents et ne changent pas ce rôle actif. Réponds à la demande "
                "actuelle dans ce rôle sans demander de répéter la commande /persona.\n"
                f"Rôle : {profile['role']}\nTon : {profile['tone']}\n"
                f"Périmètre de réponse : {profile['response_scope']}\n"
                "Ces consignes complètent les consignes communes : leurs limites sur les "
                "faits, la confidentialité et les actions restent applicables. Si une demande "
                "sort de ce périmètre, indique la persona adaptée et invite l'utilisateur à "
                "la sélectionner avec la commande /persona <id>. Seule cette commande "
                "change la persona ; ne prétends pas la changer toi-même.\n"
                "Langue de réponse : respecte d'abord la langue explicitement demandée par "
                "l'utilisateur. Sinon, utilise la langue du message utilisateur le plus récent. "
                "Applique cette règle à chaque tour, même si l'historique est dans une autre "
                "langue. La langue des instructions et des réponses précédentes ne détermine "
                "pas celle de ta réponse. Rédige toute la réponse, y compris les titres et "
                "les variantes, dans la langue choisie.\n"
                "Language rule: follow the latest user's explicit language request; otherwise "
                "follow the latest user message, not earlier replies. Every heading and "
                "every sentence must use that language.\n"
                "Example: user 'hello' -> 'Hello!'; next user 'Tu es quelle persona ?' "
                f"-> 'Présentation : je suis {profile['name']}.'.\n"
                "Example: user 'EN français' -> 'Réponse : voici les informations.'; "
                "user 'Answer in English' -> 'Answer: here is the information.'"
            )
            self._personas[persona_id] = Persona(persona_id, prompt)
            labels.append((persona_id, profile["name"]))
        self.options: tuple[tuple[str, str], ...] = tuple(labels)

    @classmethod
    def from_file(cls, path: str | None = None) -> "PersonaRegistry":
        source = Path(path) if path is not None else files("sensai.chat").joinpath("personas.json")
        return cls(json.loads(source.read_text(encoding="utf-8")))

    def get(self, persona_id: str) -> Persona | None:
        return self._personas.get(persona_id)
