"""Persona selection at startup and /persona switching through cli.main, with scripted clients."""

import json
from importlib.resources import files

import pytest

from fakes import FakeClient, scripted_terminal
from sensai.cli import main as cli
from sensai.chat.personas import PersonaRegistry
from sensai.chat.prompts import load_system_prompt
from sensai.chat.session import ChatSession
from sensai.settings import Settings
from sensai.core import cancellation
from sensai.core.cancellation import CancellationToken, OperationCancelled
from sensai.core.errors import LLMError

pytestmark = pytest.mark.usefixtures("isolated_settings")

BUILTINS = json.loads(files("sensai.chat").joinpath("personas.json").read_text(encoding="utf-8"))
BUILTIN_IDS = {profile["id"] for profile in BUILTINS}
PROFILE = {
    "id": "editor", "name": "Édition", "tone": "Warm", "role": "Review drafts",
    "response_scope": "Caption revisions",
}


def custom_profile(persona_id="editor"):
    return {
        "id": persona_id,
        "name": "Édition locale",
        "tone": "Direct",
        "role": "Revise draft captions",
        "response_scope": "Caption revisions only",
    }


# --- Startup selection and catalogue errors ----------------------------------------------

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
    monkeypatch.setattr(cli, "create_client", lambda _, usage_sink=None: pytest.fail("client created"))
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
    monkeypatch.setattr(cli, "create_client", lambda _, usage_sink=None: pytest.fail("client created"))
    with pytest.raises(SystemExit, match="error:"):
        cli.main(["model", *args])


@pytest.mark.parametrize("persona_id", [None, "redaction", "communaute", "analyse"])
def test_actual_model_prompt_stream_and_rollback(monkeypatch, tmp_path, persona_id):
    prompt_file = tmp_path / "system.txt"
    prompt_file.write_text("Shared facts, privacy and approval rules", encoding="utf-8")
    client = FakeClient(["first", " reply"], ["partial"], ["next"])
    settings = Settings(_env_file=None, SENSAI_PERSONA=None, SENSAI_PERSONAS_FILE=None)
    monkeypatch.setattr(cli, "Settings", lambda: settings)
    monkeypatch.setattr(cli, "create_client", lambda _, usage_sink=None: client)

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

    monkeypatch.setattr(cli, "TerminalInput", scripted_terminal(None))
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


def test_main_cli_overrides_environment_catalogue_and_selection(monkeypatch, tmp_path):
    catalogue = tmp_path / "profiles.json"
    catalogue.write_text(json.dumps([custom_profile()]), encoding="utf-8")
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Keep shared approval rules.", encoding="utf-8")
    monkeypatch.setenv("SENSAI_PERSONAS_FILE", str(tmp_path / "missing-env.json"))
    monkeypatch.setenv("SENSAI_PERSONA", "missing-env-persona")
    client = FakeClient(["draft"], ["revision"])
    monkeypatch.setattr(cli, "create_client", lambda settings, usage_sink=None: client)

    monkeypatch.setattr(cli, "TerminalInput",
                        scripted_terminal(["Write a draft", "Revise it", "exit"]))
    cli.main(["fake-model", "--prompt", str(prompt), "--personas-file", str(catalogue),
              "--persona", "editor"])
    assert len(client.calls) == 2
    transmitted_prompt = client.calls[0][0]
    assert transmitted_prompt.startswith("Keep shared approval rules.\n\nPersona: Édition locale")
    assert "Caption revisions only" in transmitted_prompt
    assert client.calls[1] == [transmitted_prompt, "Write a draft", "draft", "Revise it"]


def test_actual_repl_cancellation_keeps_persona_and_discards_partial_turn(
    monkeypatch, tmp_path, capsys
):
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Shared rules", encoding="utf-8")
    client = FakeClient(["shown partial", "never shown"], ["complete"])
    monkeypatch.setattr(cli, "create_client", lambda settings, usage_sink=None: client)
    partial_emitted = False

    class Terminal:
        def __enter__(self):
            self.inputs = iter(["Interrupted request", "Next request", "exit"])
            return self

        def __exit__(self, *args):
            pass

        def read(self, prompt):
            nonlocal partial_emitted
            partial_emitted = False
            return next(self.inputs)

        def cancel_requested(self):
            return partial_emitted and len(client.calls) == 1

    original_stream = client.stream

    def stream(model, messages, cancellation=None):
        nonlocal partial_emitted
        for chunk in original_stream(model, messages, cancellation):
            yield chunk
            if len(client.calls) == 1:
                partial_emitted = True

    client.stream = stream
    monkeypatch.setattr(cli, "TerminalInput", Terminal)
    cli.main(["fake-model", "--prompt", str(prompt), "--persona", "analyse"])
    assert len(client.calls) == 2
    assert "Persona: Analyse" in client.calls[0][0]
    assert client.calls[1] == [client.calls[0][0], "Next request"]
    output = capsys.readouterr().out
    assert "shown partial" in output
    assert "Réponse interrompue" in output
    assert "never shown" not in output
    assert "complete" in output


@pytest.mark.parametrize("contents", [
    b"\xff\xfe", b"{invalid JSON", b"[]", b"[null]",
    json.dumps([custom_profile(), custom_profile(" editor ")]).encode(),
    json.dumps([dict(custom_profile(), response_scope=None)]).encode(),
])
def test_bad_catalogue_is_explicit_startup_error_before_model_or_prompt(
    monkeypatch, tmp_path, contents
):
    path = tmp_path / "bad.json"
    path.write_bytes(contents)
    monkeypatch.setattr(cli, "create_client", lambda settings, usage_sink=None: pytest.fail("model client created"))
    monkeypatch.setattr(cli, "load_system_prompt", lambda path: pytest.fail("prompt loaded"))
    with pytest.raises(SystemExit, match="error: cannot load personas:"):
        cli.main(["fake-model", "--personas-file", str(path)])


def test_listing_custom_environment_catalogue_from_another_cwd(monkeypatch, tmp_path, capsys):
    catalogue = tmp_path / "profiles.json"
    catalogue.write_text(json.dumps([custom_profile()]), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SENSAI_PERSONAS_FILE", str(catalogue))
    monkeypatch.setenv("SENSAI_PERSONA", "unknown-selection")
    monkeypatch.setenv("SENSAI_PROMPT", "missing-prompt.txt")
    monkeypatch.setattr(cli, "create_client", lambda settings, usage_sink=None: pytest.fail("model client created"))
    monkeypatch.setattr(cli, "load_system_prompt", lambda path: pytest.fail("prompt loaded"))
    cli.main(["--list-personas"])
    assert capsys.readouterr().out.splitlines() == ["editor: Édition locale"]


@pytest.mark.parametrize("persona_id", sorted(BUILTIN_IDS))
def test_real_shared_prompt_precedes_builtin_persona_block(monkeypatch, persona_id):
    shared = load_system_prompt()
    client = FakeClient(["ok"])
    monkeypatch.setattr(cli, "create_client", lambda settings, usage_sink=None: client)
    monkeypatch.setattr(cli, "TerminalInput", scripted_terminal(["Hello", "exit"]))
    cli.main(["fake-model", "--persona", persona_id])
    system = client.requests[0][1][0].content
    persona_block = PersonaRegistry.from_file().get(persona_id).system_prompt
    assert system.startswith(shared)
    for rules in ("Facts and claims:", "Privacy:", "Instructions and actions:"):
        assert system.index(rules) < len(shared)
    assert system[len(shared):] == "\n\n" + persona_block
    assert system.count(persona_block) == 1


def test_unknown_environment_persona_fails_before_client(monkeypatch):
    monkeypatch.setenv("SENSAI_PERSONA", "ghost")
    monkeypatch.setattr(cli, "create_client", lambda settings, usage_sink=None: pytest.fail("client created"))
    with pytest.raises(SystemExit, match="^error: unknown persona: ghost$"):
        cli.main(["model"])


def test_json_object_catalogue_fails_before_client(monkeypatch, tmp_path):
    path = tmp_path / "object.json"
    path.write_text(json.dumps({"personas": [PROFILE]}), encoding="utf-8")
    monkeypatch.setattr(cli, "create_client", lambda settings, usage_sink=None: pytest.fail("client created"))
    with pytest.raises(SystemExit, match="^error: cannot load personas: .*JSON array"):
        cli.main(["model", "--personas-file", str(path)])


# --- Runtime /persona switching ------------------------------------------------------------

@pytest.mark.parametrize("initial_persona", [None, "editor"])
def test_main_switches_cached_custom_profiles_without_losing_history(
    monkeypatch, tmp_path, capsys, initial_persona
):
    profiles = [
        {"id": persona_id, "name": name, "tone": "Clear", "role": name,
         "response_scope": scope}
        for persona_id, name, scope in [
            ("editor", "Édition", "Draft captions"),
            ("Review Team", "Review", "Review supplied captions"),
        ]
    ]
    catalogue = tmp_path / "personas.json"
    catalogue.write_text(json.dumps(profiles), encoding="utf-8")
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("Shared custom instructions.", encoding="utf-8")
    registry = PersonaRegistry(profiles)
    client = FakeClient(["first", " reply"], ["revision"], ["last"])
    monkeypatch.setattr(cli, "Settings", lambda: Settings(_env_file=None, SENSAI_PERSONA=None,
                                                         SENSAI_PERSONAS_FILE=None))
    monkeypatch.setattr(cli, "create_client", lambda _, usage_sink=None: client)

    class Terminal:
        def __enter__(self):
            self.inputs = iter([
                "Draft", " /persona ", "/persona absent", "/persona redaction",
                "\t/persona\tReview Team  ", "Revise", "/persona editor",
                "/persona editor", "Finish", "exit",
            ])
            return self

        def __exit__(self, *args):
            pass

        def read(self, prompt):
            text = next(self.inputs)
            if text == " /persona ":
                catalogue.write_text("invalid JSON after startup", encoding="utf-8")
                prompt_file.write_text("Changed after startup", encoding="utf-8")
            return text

        def cancel_requested(self):
            return False

    monkeypatch.setattr(cli, "TerminalInput", Terminal)
    args = ["fake-model", "--prompt", str(prompt_file), "--personas-file", str(catalogue)]
    if initial_persona:
        args.extend(["--persona", initial_persona])
    cli.main(args)

    base = "Shared custom instructions."
    initial = base if initial_persona is None else base + "\n\n" + registry.get("editor").system_prompt
    reviewer = base + "\n\n" + registry.get("Review Team").system_prompt
    editor = base + "\n\n" + registry.get("editor").system_prompt
    assert client.calls == [
        [initial, "Draft"],
        [reviewer, "Draft", "first reply", reviewer, "Revise"],
        [editor, "Draft", "first reply", "Revise", "revision", editor, "Finish"],
    ]
    assert [message.role for message in client.requests[2][1]] == [
        "system", "user", "assistant", "user", "assistant", "system", "user",
    ]
    output = capsys.readouterr().out
    assert "editor: Édition\nReview Team: Review" in output
    assert "error: unknown persona: absent" in output
    assert "error: unknown persona: redaction" in output
    assert "Persona sélectionnée : Review Team" in output
    assert "first reply" in output and "revision" in output and "last" in output


def test_invalid_and_listing_commands_leave_existing_history_untouched(capsys):
    client = FakeClient(["reply"])
    session = ChatSession(client, "model", "Shared")
    list(session.send("Question"))
    before = list(session.messages)
    inputs = iter(["/persona", "/persona absent", "/persona redaction extra", "exit"])
    cli.repl(session, read=lambda _: next(inputs), persona_registry=PersonaRegistry.from_file(),
             base_prompt="Shared")
    assert session.messages == before
    assert len(client.calls) == 1
    assert "error: unknown persona: redaction extra" in capsys.readouterr().out


@pytest.mark.parametrize("failure, notice", [
    (OperationCancelled("cancelled"), "Réponse interrompue"),
    (LLMError("broken stream"), "error: broken stream"),
])
def test_switched_persona_survives_interrupted_stream_and_next_switch(failure, notice, capsys):
    registry = PersonaRegistry.from_file()
    client = FakeClient(["partial", failure], ["complete"])
    session = ChatSession(client, "model", "Shared")
    inputs = iter([
        "/persona analyse", "Interrupted", "/persona communaute", "Next", "exit",
    ])
    cli.repl(session, read=lambda _: next(inputs), persona_registry=registry, base_prompt="Shared")
    analyse = "Shared\n\n" + registry.get("analyse").system_prompt
    communaute = "Shared\n\n" + registry.get("communaute").system_prompt
    assert client.calls == [
        [analyse, analyse, "Interrupted"],
        [communaute, communaute, "Next"],
    ]
    assert [message.content for message in session.messages[1:]] == ["Next", "complete"]
    output = capsys.readouterr().out
    assert "partial" in output and notice in output and "complete" in output


def test_legacy_repl_rejects_persona_command_without_model_call(capsys):
    client = FakeClient(["reply"])
    session = ChatSession(client, "model", "Shared")
    inputs = iter(["/persona analyse", "/personality", "exit"])
    cli.repl(session, read=lambda _: next(inputs))
    assert client.calls == [["Shared", "/personality"]]
    assert "error: persona selection is unavailable" in capsys.readouterr().out


@pytest.mark.parametrize("interrupt, notice", [
    ("cancel", "Réponse interrompue"),
    ("timeout", "Délai maximal dépassé"),
])
def test_interrupted_switch_preserves_earlier_turn_and_streaming(monkeypatch, interrupt, notice):
    clock = 0.0
    cancelled = False
    monkeypatch.setattr(cli, "monotonic", lambda: clock)
    monkeypatch.setattr(cancellation, "monotonic", lambda: clock)
    registry = PersonaRegistry.from_file()
    client = FakeClient(["old reply"], ["partial", "discarded"], ["new", " reply"])
    session = ChatSession(client, "model", "Shared")
    inputs = iter([
        "Earlier", "/persona analyse", "Interrupted", "/persona absent",
        "/persona communaute", "Continue", "exit",
    ])
    output = []

    def read(_):
        nonlocal cancelled
        cancelled = False
        return next(inputs)

    def write(text="", **kwargs):
        nonlocal clock, cancelled
        output.append(text)
        if text == "partial":
            if interrupt == "cancel":
                cancelled = True
            else:
                clock += 121.0

    cli.repl(session, read=read, write=write, cancel_requested=lambda: cancelled,
             persona_registry=registry, base_prompt="Shared")

    analyse = "Shared\n\n" + registry.get("analyse").system_prompt
    communaute = "Shared\n\n" + registry.get("communaute").system_prompt
    assert client.calls == [
        ["Shared", "Earlier"],
        [analyse, "Earlier", "old reply", analyse, "Interrupted"],
        [communaute, "Earlier", "old reply", communaute, "Continue"],
    ]
    assert [message.content for message in session.messages[1:]] == [
        "Earlier", "old reply", "Continue", "new reply",
    ]
    assert "discarded" not in output
    assert any(notice in text for text in output)
    assert output[-3:-1] == ["new", " reply"]


def test_cli_recovers_from_empty_reply_and_honors_two_persona_switches():
    registry = PersonaRegistry.from_file()
    client = FakeClient(["Je suis Rédaction."], [], ["New", " answer"])
    session = ChatSession(client, "model", "Shared\n\n" + registry.get("redaction").system_prompt)
    inputs = iter([
        "Earlier", "/persona analyse", "Failed", "/persona communaute", "Continue", "exit",
    ])
    output = []
    cli.repl(session, read=lambda _: next(inputs),
             write=lambda text="", **kwargs: output.append(text),
             persona_registry=registry, base_prompt="Shared")

    analyse_prompt = "Shared\n\n" + registry.get("analyse").system_prompt
    communaute_prompt = "Shared\n\n" + registry.get("communaute").system_prompt
    assert client.calls[1] == [
        analyse_prompt, "Earlier", "Je suis Rédaction.", analyse_prompt, "Failed",
    ]
    assert client.calls[2] == [
        communaute_prompt, "Earlier", "Je suis Rédaction.", communaute_prompt, "Continue",
    ]
    assert [message.role for message in client.requests[2][1]] == [
        "system", "user", "assistant", "system", "user",
    ]
    assert session.messages[0].content == communaute_prompt
    assert [message.content for message in session.messages[1:]] == [
        "Earlier", "Je suis Rédaction.", "Continue", "New answer",
    ]
    assert output.count("Persona sélectionnée : analyse") == 1
    assert output.count("Persona sélectionnée : communaute") == 1
    assert sum(text.startswith("error:") and "no visible answer" in text for text in output) == 1
    assert output[-3:-1] == ["New", " answer"]


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
    monkeypatch.setattr(cli, "create_client", lambda settings, usage_sink=None: client)
    monkeypatch.setattr(cli, "TerminalInput", scripted_terminal([
        "Turn one", "/persona analyse", "Turn two", "/persona communaute", "Turn three", "exit",
    ], on_read=lambda: snapshots.append(list(sessions[0].messages))))
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
