"""T25 gap-closing persona regressions: creation, switching, errors and B1 streaming."""

import json
import os
import re
from importlib.resources import files
from pathlib import Path

import pytest

from fakes import FakeClient
from sensai.app import cli
from sensai.app.personas import PersonaRegistry
from sensai.app.session import ChatSession
from sensai.app.settings import Settings

ROOT = Path(__file__).resolve().parents[3]
BUILTINS = json.loads(files("sensai.app").joinpath("personas.json").read_text(encoding="utf-8"))
BUILTIN_IDS = {profile["id"] for profile in BUILTINS}
PROFILE = {
    "id": "editor", "name": "Édition", "tone": "Warm", "role": "Review drafts",
    "response_scope": "Caption revisions",
}


@pytest.fixture(autouse=True)
def isolated_configuration(monkeypatch):
    for name in list(os.environ):
        if name.startswith("SENSAI_") or name == "OLLAMA_HOST":
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(cli, "Settings", lambda: Settings(_env_file=None))


def scripted_terminal(monkeypatch, inputs, on_read=lambda: None):
    class Terminal:
        def __enter__(self):
            self.inputs = iter(inputs)
            return self

        def __exit__(self, *args):
            pass

        def read(self, prompt):
            on_read()
            return next(self.inputs)

        def cancel_requested(self):
            return False

    monkeypatch.setattr(cli, "TerminalInput", Terminal)


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


@pytest.mark.parametrize("persona_id", sorted(BUILTIN_IDS))
def test_real_shared_prompt_precedes_builtin_persona_block(monkeypatch, persona_id):
    shared = (ROOT / "prompts" / "system.txt").read_text(encoding="utf-8").strip()
    client = FakeClient(["ok"])
    monkeypatch.setattr(cli, "create_client", lambda settings: client)
    scripted_terminal(monkeypatch, ["Hello", "exit"])
    cli.main(["fake-model", "--prompt", str(ROOT / "prompts" / "system.txt"),
              "--persona", persona_id])
    system = client.requests[0][1][0].content
    persona_block = PersonaRegistry.from_file().get(persona_id).system_prompt
    assert system.startswith(shared)
    for rules in ("Facts and claims:", "Privacy:", "Instructions and actions:"):
        assert system.index(rules) < len(shared)
    assert system[len(shared):] == "\n\n" + persona_block
    assert system.count(persona_block) == 1


def test_whitespace_only_id_is_rejected():
    with pytest.raises(ValueError, match="id must be a nonempty string"):
        PersonaRegistry([dict(PROFILE, id=" \t\n")])


def test_unknown_environment_persona_fails_before_client(monkeypatch):
    monkeypatch.setenv("SENSAI_PERSONA", "ghost")
    monkeypatch.setattr(cli, "create_client", lambda settings: pytest.fail("client created"))
    with pytest.raises(SystemExit, match="^error: unknown persona: ghost$"):
        cli.main(["model"])


def test_json_object_catalogue_fails_before_client(monkeypatch, tmp_path):
    path = tmp_path / "object.json"
    path.write_text(json.dumps({"personas": [PROFILE]}), encoding="utf-8")
    monkeypatch.setattr(cli, "create_client", lambda settings: pytest.fail("client created"))
    with pytest.raises(SystemExit, match="^error: cannot load personas: .*JSON array"):
        cli.main(["model", "--personas-file", str(path)])


def test_builtin_switches_through_main_keep_identical_completed_turns(
    monkeypatch, tmp_path, capsys
):
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Shared rules", encoding="utf-8")
    client = FakeClient(["Reply", " one"], ["Reply two"], ["Reply three"])
    sessions, snapshots = [], []

    def make_session(*args):
        sessions.append(ChatSession(*args))
        return sessions[-1]

    monkeypatch.setattr(cli, "ChatSession", make_session)
    monkeypatch.setattr(cli, "create_client", lambda settings: client)
    scripted_terminal(monkeypatch, [
        "Turn one", "/persona analyse", "Turn two", "/persona communaute", "Turn three", "exit",
    ], on_read=lambda: snapshots.append(list(sessions[0].messages)))
    cli.main(["fake-model", "--prompt", str(prompt), "--persona", "redaction"])

    registry = PersonaRegistry.from_file()
    red, ana, com = ("Shared rules\n\n" + registry.get(pid).system_prompt
                     for pid in ("redaction", "analyse", "communaute"))
    shape = [[(m.role, m.content) for m in request] for _, request in client.requests]
    assert shape == [
        [("system", red), ("user", "Turn one")],
        [("system", ana), ("user", "Turn one"), ("assistant", "Reply one"),
         ("system", ana), ("user", "Turn two")],
        [("system", com), ("user", "Turn one"), ("assistant", "Reply one"),
         ("user", "Turn two"), ("assistant", "Reply two"), ("system", com),
         ("user", "Turn three")],
    ]
    after_one, after_two = snapshots[1], snapshots[3]
    assert all(a is b for a, b in zip(client.requests[1][1][1:3], after_one[1:3]))
    assert all(a is b for a, b in zip(client.requests[2][1][1:5], after_two[1:5]))
    final = sessions[0].messages
    assert all(a is b for a, b in zip(final[1:5], after_two[1:5]))
    assert [(m.role, m.content) for m in final] == [
        ("system", com), ("user", "Turn one"), ("assistant", "Reply one"),
        ("user", "Turn two"), ("assistant", "Reply two"),
        ("user", "Turn three"), ("assistant", "Reply three"),
    ]
    sent = [m for _, request in client.requests for m in request]
    assert not any(m.content.lstrip().startswith("/persona") for m in sent)
    assert {m.content for m in sent if m.role == "user"} == {"Turn one", "Turn two", "Turn three"}
    output = capsys.readouterr().out
    assert "Persona sélectionnée : analyse" in output
    assert "Persona sélectionnée : communaute" in output


class RecordingClient(FakeClient):
    """Logs each chunk when the consumer pulls it, before handing it over."""

    def __init__(self, events, *replies):
        super().__init__(*replies)
        self.events = events

    def stream(self, model, messages, cancellation=None):
        for chunk in super().stream(model, messages, cancellation):
            self.events.append(("pull", chunk))
            yield chunk


def test_chunks_are_written_and_flushed_before_the_next_pull_with_and_without_persona():
    events = []
    client = RecordingClient(events, ["Hel", "lo", "!"], ["Ana", "ly", "se"])
    session = ChatSession(client, "model", "Shared")
    inputs = iter(["First", "/persona analyse", "Second", "exit"])
    cli.repl(session, read=lambda _: next(inputs),
             write=lambda text="", **kwargs: events.append(("write", text, kwargs)),
             persona_registry=PersonaRegistry.from_file(), base_prompt="Shared")

    def streamed(*chunks):
        return [event for chunk in chunks
                for event in (("pull", chunk), ("write", chunk, {"end": "", "flush": True}))]

    assert events == [
        *streamed("Hel", "lo", "!"), ("write", "", {}),
        ("write", "Persona sélectionnée : analyse", {}),
        *streamed("Ana", "ly", "se"), ("write", "", {}),
    ]
    assert [m.role for m in client.requests[1][1]] == [
        "system", "user", "assistant", "system", "user",
    ]


def test_no_persona_multi_turn_session_never_gets_a_reminder():
    client = FakeClient(["A1"], ["A2"], ["A3"])
    session = ChatSession(client, "model", "Shared")
    inputs = iter(["Q1", "/persona", "Q2", "/persona absent", "Q3", "exit"])
    cli.repl(session, read=lambda _: next(inputs), write=lambda *args, **kwargs: None,
             persona_registry=PersonaRegistry.from_file(), base_prompt="Shared")
    assert client.calls == [
        ["Shared", "Q1"],
        ["Shared", "Q1", "A1", "Q2"],
        ["Shared", "Q1", "A1", "Q2", "A2", "Q3"],
    ]
    for _, request in client.requests:
        roles = [m.role for m in request]
        assert roles == ["system"] + ["user", "assistant"] * (len(roles) // 2 - 1) + ["user"]
