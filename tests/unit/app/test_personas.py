import json

import pytest

from sensai.app import cli
from sensai.app.personas import PersonaRegistry
from sensai.app.session import ChatSession
from sensai.app.settings import Settings
from sensai.core.cancellation import CancellationToken, OperationCancelled
from sensai.core.contracts import PersonaPort
from fakes import FakeClient


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
        assert "language of the user's message" in persona.system_prompt
        assert "next launch" in persona.system_prompt


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


def test_settings_cli_priority(monkeypatch):
    monkeypatch.setenv("SENSAI_PERSONA", "analyse")
    monkeypatch.setenv("SENSAI_PERSONAS_FILE", "environment.json")
    settings = Settings(_env_file=None)
    env_args = cli.parse_args(settings, ["model"])
    assert (env_args.persona, env_args.personas_file) == ("analyse", "environment.json")
    cli_args = cli.parse_args(settings, ["model", "--persona", "editor",
                                            "--personas-file", "custom.json"])
    assert (cli_args.persona, cli_args.personas_file) == ("editor", "custom.json")


def test_listing_needs_no_model_or_client(monkeypatch, capsys):
    monkeypatch.setattr(cli, "Settings", lambda: Settings(_env_file=None, SENSAI_MODEL=None,
                                                         SENSAI_PERSONA="unknown"))
    monkeypatch.setattr(cli, "create_client", lambda _: pytest.fail("client created"))
    monkeypatch.setattr(cli, "load_system_prompt", lambda _: pytest.fail("prompt read"))
    cli.main(["--list-personas"])
    assert capsys.readouterr().out.splitlines() == [
        "redaction: Rédaction", "communaute: Communauté", "analyse: Analyse",
    ]


@pytest.mark.parametrize("args", [
    ["--persona", "absent"], ["--personas-file", "absent.json"],
])
def test_invalid_startup_fails_before_client(monkeypatch, args):
    monkeypatch.setattr(cli, "Settings", lambda: Settings(_env_file=None))
    monkeypatch.setattr(cli, "create_client", lambda _: pytest.fail("client created"))
    with pytest.raises(SystemExit, match="error:"):
        cli.main(["model", *args])


@pytest.mark.parametrize("persona_id", [None, "redaction", "communaute", "analyse"])
def test_actual_model_prompt_stream_and_rollback(monkeypatch, tmp_path, persona_id):
    prompt_file = tmp_path / "system.txt"
    prompt_file.write_text("Shared facts, privacy and approval rules", encoding="utf-8")
    client = FakeClient(["first", " reply"], ["partial"], ["next"])
    settings = Settings(_env_file=None, SENSAI_PERSONA=None, SENSAI_PERSONAS_FILE=None)
    monkeypatch.setattr(cli, "Settings", lambda: settings)
    monkeypatch.setattr(cli, "create_client", lambda _: client)

    class Terminal:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, prompt):
            pytest.fail("unexpected terminal read")

        def cancel_requested(self):
            return False

    def exercise(session: ChatSession, **kwargs):
        assert list(session.send("first message")) == ["first", " reply"]
        token = CancellationToken()
        stream = session.send("cancel this", token)
        assert next(stream) == "partial"
        token.cancel()
        with pytest.raises(OperationCancelled):
            next(stream)
        assert list(session.send("next message")) == ["next"]
        assert [message.content for message in session.messages[1:]] == [
            "first message", "first reply", "next message", "next"
        ]

    monkeypatch.setattr(cli, "TerminalInput", Terminal)
    monkeypatch.setattr(cli, "repl", exercise)
    args = ["model", "--prompt", str(prompt_file)]
    if persona_id:
        args.extend(["--persona", persona_id])
    cli.main(args)
    transmitted = client.requests[0][1][0].content
    if persona_id:
        assert transmitted == (
            "Shared facts, privacy and approval rules\n\n"
            + PersonaRegistry.from_file().get(persona_id).system_prompt
        )
    else:
        assert transmitted == "Shared facts, privacy and approval rules"
