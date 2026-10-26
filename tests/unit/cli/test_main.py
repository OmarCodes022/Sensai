"""cli.main argument parsing, default prompt and REPL notices, with scripted clients."""

import io

import pytest

from fakes import FakeClient, scripted_terminal
from sensai.chat.prompts import load_system_prompt
from sensai.cli import main as cli
from sensai.cli.main import parse_args, repl
from sensai.chat.session import ChatSession
from sensai.settings import Settings
from sensai.core.cancellation import OperationCancelled, OperationTimedOut


def test_cli_model_argument_overrides_settings():
    args = parse_args(Settings(_env_file=None, SENSAI_MODEL="env-model"), ["arg-model"])
    assert args.model == "arg-model"


def test_cli_requires_a_model(monkeypatch):
    monkeypatch.delenv("SENSAI_MODEL", raising=False)
    with pytest.raises(SystemExit):
        parse_args(Settings(_env_file=None), [])


@pytest.mark.parametrize("error, notice", [(OperationCancelled, "Réponse interrompue"), (OperationTimedOut, "Délai maximal dépassé")])
def test_repl_input_cancel_then_partial_turn_notice_and_next_prompt(error, notice):
    reads = iter([KeyboardInterrupt(), "hi", "next", "quit"])
    output = io.StringIO()
    client = FakeClient(["partial", error("interrupted")], ["complete"])
    session = ChatSession(client, "model", "sys")

    def read(prompt):
        value = next(reads)
        if isinstance(value, BaseException):
            raise value
        return value

    def write(*args, **kwargs):
        print(*args, file=output, **kwargs)

    repl(session, read=read, write=write)
    text = output.getvalue()
    assert "interrompre la réponse" not in text
    assert f"partial\n{notice}" in text
    assert text.endswith("complete\n")
    assert [message.content for message in session.messages] == ["sys", "next", "complete"]
    assert client.calls[-1] == ["sys", "next"]


def test_operation_timeout_env_and_cli_precedence(monkeypatch):
    monkeypatch.setenv("SENSAI_OPERATION_TIMEOUT", "17")
    settings = Settings(_env_file=None)
    assert settings.operation_timeout == 17
    assert parse_args(settings, ["model"]).operation_timeout == 17
    assert parse_args(settings, ["model", "--operation-timeout", "2.5"]).operation_timeout == 2.5


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "-inf"])
def test_operation_timeout_rejects_invalid_cli_and_env_values(value, monkeypatch):
    from pydantic import ValidationError

    settings = Settings(_env_file=None)
    with pytest.raises(SystemExit):
        parse_args(settings, ["model", "--operation-timeout", value])
    monkeypatch.setenv("SENSAI_OPERATION_TIMEOUT", value)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.usefixtures("isolated_settings")
@pytest.mark.parametrize("source", ["default", "cli", "env"])
def test_default_prompt_is_packaged_and_overrides_still_apply(monkeypatch, tmp_path, source):
    monkeypatch.chdir(tmp_path)  # no prompts/ directory here
    custom = tmp_path / "custom.txt"
    custom.write_text("Custom rules\n", encoding="utf-8")
    argv = ["model"]
    if source == "cli":
        argv += ["--prompt", str(custom)]
    elif source == "env":
        monkeypatch.setenv("SENSAI_PROMPT", str(custom))
    client = FakeClient(["ok"])
    monkeypatch.setattr(cli, "create_client", lambda settings, usage_sink=None: client)
    monkeypatch.setattr(cli, "TerminalInput", scripted_terminal(["Hi", "exit"]))
    cli.main(argv)
    expected = load_system_prompt() if source == "default" else "Custom rules"
    assert client.calls == [[expected, "Hi"]]


@pytest.mark.usefixtures("isolated_settings")
@pytest.mark.parametrize("case", ["cli-wins-over-env", "empty-env", "empty-cli"])
def test_prompt_option_precedence_and_empty_values(monkeypatch, tmp_path, case):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "cli.txt").write_text("CLI rules\n", encoding="utf-8")
    (tmp_path / "env.txt").write_text("Env rules\n", encoding="utf-8")
    argv, expected = ["model"], load_system_prompt()
    if case == "cli-wins-over-env":
        monkeypatch.setenv("SENSAI_PROMPT", str(tmp_path / "env.txt"))
        argv += ["--prompt", str(tmp_path / "cli.txt")]
        expected = "CLI rules"
    elif case == "empty-env":
        monkeypatch.setenv("SENSAI_PROMPT", "")
    else:
        argv += ["--prompt", ""]
    client = FakeClient(["ok"])
    monkeypatch.setattr(cli, "create_client", lambda settings, usage_sink=None: client)
    monkeypatch.setattr(cli, "TerminalInput", scripted_terminal(["Hi", "exit"]))
    cli.main(argv)
    assert client.calls == [[expected, "Hi"]]
