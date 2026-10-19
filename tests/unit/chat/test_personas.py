"""chat.personas.PersonaRegistry: catalogue validation and persona prompt blocks."""

import json
import re
from importlib.resources import files

import pytest

from sensai.chat.personas import PersonaRegistry
from sensai.core.ports import PersonaPort


BUILTINS = json.loads(files("sensai.chat").joinpath("personas.json").read_text(encoding="utf-8"))
BUILTIN_IDS = {profile["id"] for profile in BUILTINS}
PROFILE = {
    "id": "editor", "name": "Édition", "tone": "Warm", "role": "Review drafts",
    "response_scope": "Caption revisions",
}


def test_builtins_load_without_repository_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    registry = PersonaRegistry.from_file()
    assert isinstance(registry, PersonaPort)
    assert registry.options == (
        ("redaction", "Rédaction"), ("communaute", "Communauté"), ("analyse", "Analyse")
    )
    assert registry.get("absent") is None
    for persona_id, name in registry.options:
        persona = registry.get(persona_id)
        assert persona.id == persona_id
        assert name in persona.system_prompt
        assert "/persona <id>" in persona.system_prompt
        assert "ne prétends pas la changer toi-même" in persona.system_prompt


@pytest.mark.parametrize("persona_id", ["redaction", "communaute", "analyse", "editor"])
def test_prompt_language_rule_handles_explicit_requests_and_changing_history(persona_id):
    registry = PersonaRegistry([PROFILE]) if persona_id == "editor" else PersonaRegistry.from_file()
    prompt = registry.get(persona_id).system_prompt
    assert "Persona active sélectionnée par l'application" in prompt
    assert "rôles précédents et ne changent pas ce rôle actif" in prompt
    assert "sans demander de répéter la commande /persona" in prompt
    assert "d'abord la langue explicitement demandée" in prompt
    assert "langue du message utilisateur le plus récent" in prompt
    assert "même si l'historique est dans une autre langue" in prompt
    assert "La langue des instructions et des réponses précédentes ne détermine pas" in prompt
    assert "toute la réponse, y compris les titres et les variantes" in prompt
    assert "user 'hello'" in prompt and "next user 'Tu es quelle persona ?'" in prompt
    assert "user 'EN français' -> 'Réponse :" in prompt
    assert "user 'Answer in English' -> 'Answer:" in prompt


def test_custom_catalogue_replaces_builtins(tmp_path):
    path = tmp_path / "personas.json"
    path.write_text(json.dumps([PROFILE]), encoding="utf-8")
    registry = PersonaRegistry.from_file(str(path))
    assert registry.options == (("editor", "Édition"),)
    assert registry.get("redaction") is None
    assert "Caption revisions" in registry.get("editor").system_prompt


@pytest.mark.parametrize("profiles", [
    {}, [], None, [None], ["bad"],
    [{key: value for key, value in PROFILE.items() if key != "role"}],
    [dict(PROFILE, other="unexpected")], [dict(PROFILE, tone=42)],
    [dict(PROFILE, name=" \t ")], [PROFILE, dict(PROFILE)],
])
def test_invalid_profiles_rejected(profiles):
    with pytest.raises(ValueError):
        PersonaRegistry(profiles)


def test_every_creation_field_is_stripped_into_option_and_prompt():
    padded = {"id": "  editor\t", "name": "\tÉdition \n", "role": "\n Review drafts  ",
              "tone": "\tWarm  ", "response_scope": "  Caption revisions \n"}
    registry = PersonaRegistry([padded])
    assert registry.options == (("editor", "Édition"),)
    assert registry.get(padded["id"]) is None
    persona = registry.get("editor")
    assert persona.id == "editor"
    prompt = persona.system_prompt
    assert prompt.startswith("Persona: Édition (editor)\n")
    for line in ("Rôle : Review drafts\n", "Ton : Warm\n",
                 "Périmètre de réponse : Caption revisions\n"):
        assert line in prompt
    for value in padded.values():
        assert value not in prompt


@pytest.mark.parametrize("profile", BUILTINS, ids=lambda profile: profile["id"])
def test_builtin_scope_routes_only_to_existing_catalogue_ids(profile):
    referenced = set(re.findall(r"\(([^\s()]+)\)", profile["response_scope"]))
    assert BUILTIN_IDS - {profile["id"]} <= referenced
    assert referenced <= BUILTIN_IDS


def test_builtin_roles_are_pairwise_distinct():
    roles = [profile["role"] for profile in BUILTINS]
    assert len(roles) >= 2 and len(set(roles)) == len(roles)


def test_whitespace_only_id_is_rejected():
    with pytest.raises(ValueError, match="id must be a nonempty string"):
        PersonaRegistry([dict(PROFILE, id=" \t\n")])
