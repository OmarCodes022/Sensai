"""T21 CLI edge cases: the whole attempt budget, refused or invalid calls, display, prompt, saving."""

import json
import os
from pathlib import Path
import tempfile
import time

import pytest

from fakes import FakeClient, FakeSessionStore, scripted_terminal
from sensai.chat import saved_sessions
from sensai.chat.prompts import load_system_prompt
from sensai.chat.saved_sessions import SessionRecorder
from sensai.chat.session import ChatSession
from sensai.cli import main as cli
from sensai.core.ports import ApprovalDecision, ToolResult
from sensai.memory.sqlite_store import StorageRepository
from sensai.sandbox import FIX_IT, PREFIX, RUN_PYTHON, SandboxRun, model_report
from sensai.tools import ToolRegistry

pytestmark = pytest.mark.usefixtures("isolated_settings")
FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
NAMES = "Data files available to run_python: brand.json, dms.json, engagement.csv, posts.json."
BULLET = ("- When a number must be computed from a data file, call run_python with code that prints "
          "the result and answer with the number it printed. If a run fails, read the error, fix "
          "the code and run it again; when the attempts run out, report the last error instead of "
          "guessing.")
STOP = ("Stopped after 3 attempts: answer with the last result or error, "
        "without calling run_python again.")
ROUND_NOTE = "Tool round limit reached. Give a final answer without tools."


@pytest.fixture(autouse=True)
def temp_root(tmp_path, monkeypatch):
    root = tmp_path / "temp-root"
    root.mkdir()
    monkeypatch.setenv("TMPDIR", str(root))
    monkeypatch.setattr(tempfile, "tempdir", str(root))
    yield root
    assert not [p for p in root.iterdir() if p.name.startswith(PREFIX)]


class Approval:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.requests = []

    def request(self, request):
        self.requests.append(request.resource)
        return ApprovalDecision(self.answers.pop(0))


def tool_call(code=None, **arguments):
    if code is not None:
        arguments["code"] = code
    return [json.dumps({"tool": "run_python", "arguments": arguments})]


def chat(inputs, client, approval=None, registry=None, **options):
    session = ChatSession(client, "model", "sys")
    lines = []
    reads = iter([*inputs, "exit"])
    registry = registry or cli._tools(lambda prompt: pytest.fail("plain reader used"),
                                      approval=approval, data_dir=str(FIXTURES))
    cli.repl(session, read=lambda prompt: next(reads), tool_registry=registry,
             write=lambda *args, **kwargs: lines.append(" ".join(map(str, args))), **options)
    return "\n".join(lines), session


def sent(client):
    return [request[-1].content for _, request in client.requests[1:]]


def tool_lines(output):
    return [line for line in output.split("\n") if line.startswith("Using tool")]


# --- the whole budget in one question ----------------------------------------------------

def test_five_calls_run_three_times_stop_twice_then_the_next_question_starts_over():
    client = FakeClient(tool_call("1 / 0"), tool_call("import nope"), tool_call("print(42)"),
                        tool_call("print(43)"), tool_call("print(44)"), ["It is 42."],
                        tool_call("print(7)"), ["Seven."])
    approval = Approval(True, True, True, True)
    output, session = chat(["Compute", "Again"], client, approval)
    assert len(approval.requests) == 4  # 3 runs, then 1 in the second question.
    shown = tool_lines(output)
    assert [line.split(" · ")[1] for line in shown[:3]] == ["Run 1", "Run 2", "Run 3"]
    assert shown[3:5] == ["Using tool: run_python · Stopped after 3 attempts"] * 2
    assert shown[5].startswith("Using tool: run_python · Run 1 · Exit code 0 · ")
    messages = sent(client)
    assert messages[3] == f"Tool error from run_python:\n{STOP}"
    assert messages[4] == f"Tool error from run_python:\n{STOP}\n{ROUND_NOTE}"
    assert messages[6].startswith("Tool result from run_python:\nAttempt 1 of 3 · Exit code 0")
    assert "stdout:\n43" not in "".join(messages)
    assert "It is 42." in output and session.messages[-1].content == "Seven."


def test_refusals_use_the_attempts_and_the_fourth_call_asks_nothing(tmp_path):
    marker = tmp_path / "ran"
    code = f"open({str(marker)!r}, 'w')"
    client = FakeClient(*[tool_call(code)] * 4, ["I could not run it."])
    approval = Approval(False, False, False)
    output, _ = chat(["Compute"], client, approval)
    assert len(approval.requests) == 3 and not marker.exists()
    assert tool_lines(output) == [
        *[f"Using tool: run_python · Run {n} · tool approval refused" for n in (1, 2, 3)],
        "Using tool: run_python · Stopped after 3 attempts"]
    last = ("\nThis was the last attempt: answer with this result or error, "
            "without calling run_python again.")
    assert sent(client)[:3] == [
        f"Tool error from run_python:\nAttempt {n} of 3 · tool approval refused{last * (n == 3)}"
        for n in (1, 2, 3)]


def test_invalid_arguments_count_without_asking_and_the_next_valid_call_is_run_two():
    client = FakeClient(tool_call(), tool_call("print(1)", extra=1), tool_call("print(5)"),
                        ["Five."])
    approval = Approval(True)
    output, _ = chat(["Compute"], client, approval)
    assert len(approval.requests) == 1
    assert tool_lines(output)[:2] == [
        "Using tool: run_python · Run 1 · invalid arguments: missing required property code",
        "Using tool: run_python · Run 2 · invalid arguments: unexpected property extra"]
    assert tool_lines(output)[2].startswith("Using tool: run_python · Run 3 · Exit code 0 · ")
    assert sent(client)[0] == ("Tool error from run_python:\nAttempt 1 of 3 · "
                               "invalid arguments: missing required property code")


def test_a_malformed_block_does_not_use_an_attempt():
    client = FakeClient(['{"tool": ""}'], tool_call("print(2)"), ["Two."])
    output, _ = chat(["Compute"], client, Approval(True))
    assert tool_lines(output)[0] == "Using tool: <invalid>({})"
    assert tool_lines(output)[1].startswith("Using tool: run_python · Run 1 · Exit code 0")


def test_history_hides_the_prefixed_tool_messages():
    client = FakeClient(tool_call("1 / 0"), tool_call("print(3)"), ["Three."])
    output, session = chat(["What is it?", "/history"], client, Approval(True, True))
    assert any(m.content.startswith("Tool error from run_python:\nAttempt 1 of 3")
               for m in session.messages)
    assert output.rstrip().endswith("\n1. What is it?")
    assert saved_sessions.user_messages(session.messages) == ["What is it?"]


def test_a_time_limit_run_is_shown_without_a_detail_line():
    from sandbox_handlers import fast_python_tool
    registry = ToolRegistry(Approval(True))
    registry.register(RUN_PYTHON, fast_python_tool, confirm=True, max_calls=3)
    client = FakeClient(tool_call("import time\ntime.sleep(30)"), ["Too slow."])
    output, _ = chat(["Compute"], client, registry=registry)
    lines = output.split("\n")
    index = next(i for i, line in enumerate(lines) if line.startswith("Using tool"))
    assert lines[index].startswith("Using tool: run_python · Run 1 · Exit code -9 · ")
    assert lines[index + 1] == "Too slow."
    assert "Time limit reached (1.5 s)" in sent(client)[0]


# --- the display stays sanitized, one line each -------------------------------------------

def crafted(*texts):
    """A run_python registry whose handler returns the given texts as error reports."""
    replies = list(texts)

    def handler(arguments, cancellation=None):
        text = replies.pop(0)
        return ToolResult(text, text if not text.startswith("Exit code 0 ") else None)

    registry = ToolRegistry()
    registry.register(RUN_PYTHON, handler, timeout=None, max_calls=3)
    return registry


def report(stdout="", stderr="", exit_code=1):
    return model_report(SandboxRun(stdout, stderr, exit_code, .1, False, False))


@pytest.mark.parametrize("text, second", [
    (report("", "\x1b[31mKeyError\x1b[0m: ‮'x'\n"), "\\x1b[31mKeyError\\x1b[0m: \\u202e'x'"),
    (report("", "a\rb\r\x07Error\n"), "\\x07Error"),
    (report("", "E" * 10_000), "E" * 160),
    (report("é" * 400 + "\n", "", 0), "é" * 160),
    (report("", "", 0), None),
    (report("out\n", "", 1), None),
])
def test_display_is_sanitized_cut_and_never_more_than_two_lines(text, second):
    client = FakeClient(tool_call("x"), ["Done."])
    output, _ = chat(["Compute"], client, registry=crafted(text))
    lines = output.split("\n")
    index = next(i for i, line in enumerate(lines) if line.startswith("Using tool"))
    assert lines[index] == f"Using tool: run_python · Run 1 · {text.split(chr(10))[0]}"
    assert lines[index + 1:index + 2] == ([second] if second is not None else ["Done."])
    assert all(line.isprintable() for line in lines[index:index + 2])


def test_control_characters_in_a_first_line_are_escaped():
    client = FakeClient(tool_call("x"), ["Done."])
    output, _ = chat(["Compute"], client, registry=crafted("cannot read data folder: \x1b[2J\rx"))
    assert "Using tool: run_python · Run 1 · cannot read data folder: \\x1b[2J" in output
    assert "\x1b" not in output and "\r" not in output


# --- Ctrl+C and saving ---------------------------------------------------------------------

def test_ctrl_c_during_the_second_run_saves_nothing_and_the_next_turn_is_clean(tmp_path):
    marker = tmp_path / "pid"
    slow = (f"import os, time\nopen({str(marker)!r}, 'w').write(str(os.getpid()))\n"
            "time.sleep(100)\n")
    store = FakeSessionStore()
    recorder = SessionRecorder(store, "s1", title="t")
    client = FakeClient(tool_call("1 / 0"), tool_call(slow), tool_call("print(9)"), ["Nine."])
    started = time.monotonic()
    output, session = chat(["Go", "Retry"], client, Approval(True, True, True), recorder=recorder,
                           cancel_requested=lambda: marker.exists() and marker.read_text() != ""
                           and not marker.with_suffix(".done").exists()
                           and not marker.with_suffix(".done").touch())
    assert time.monotonic() - started < 15
    assert "Réponse interrompue" in output
    with pytest.raises(ProcessLookupError):
        os.kill(int(marker.read_text()), 0)
    saved = [m.content for m in store.sessions["s1"].messages]
    assert saved[0] == "Retry" and "Go" not in saved and slow not in "".join(saved)
    assert saved[2].startswith("Tool result from run_python:\nAttempt 1 of 3 · Exit code 0")
    assert tool_lines(output)[-1].startswith("Using tool: run_python · Run 1 · Exit code 0")


def test_ctrl_c_during_the_first_question_saves_no_session_at_all(tmp_path):
    marker = tmp_path / "pid"
    slow = f"open({str(marker)!r}, 'w').write('1')\nimport time\ntime.sleep(100)\n"
    store = FakeSessionStore()
    client = FakeClient(tool_call("1 / 0"), tool_call(slow))
    output, _ = chat(["Go"], client, Approval(True, True), recorder=SessionRecorder(store, "s1"),
                     cancel_requested=lambda: marker.exists() and marker.read_text() != "")
    assert "Réponse interrompue" in output and store.sessions == {}


# --- through cli.main: the data-file line in the system prompt ---------------------------

@pytest.fixture
def main_chat(monkeypatch, tmp_path):
    monkeypatch.setattr(saved_sessions, "new_session_id", lambda exists: "k7f2qa")

    def run(client, inputs, *argv, data_dir=FIXTURES):
        if data_dir is not None:
            monkeypatch.setenv("SENSAI_DATA_DIR", str(data_dir))
        else:
            monkeypatch.delenv("SENSAI_DATA_DIR", raising=False)
        monkeypatch.setattr(cli, "create_client", lambda settings: client)
        monkeypatch.setattr(cli, "TerminalInput", scripted_terminal([*inputs, "exit"]))
        cli.main(["model", "--db", str(tmp_path / "s.db"), *argv])
    return run


def test_packaged_prompt_has_the_bullet_once():
    prompt = load_system_prompt(None)
    assert prompt.count(BULLET) == 1
    assert prompt.index("Instructions and actions:") < prompt.index(BULLET)


def test_data_line_sits_after_the_prompt_and_before_profile_persona_and_tools(main_chat, tmp_path):
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps({"ton": "direct"}), encoding="utf-8")
    client = FakeClient(["Hi."])
    main_chat(client, ["Hello"], "--profile-file", str(profile), "--persona", "analyse")
    system = client.requests[0][1][0].content
    prompt = load_system_prompt(None)
    assert system.startswith(f"{prompt}\n\n{NAMES}\n\n{saved_sessions.PROFILE_HEADER}")
    assert system.count(NAMES) == 1
    assert system.index(NAMES) < system.index("Available tools")


def test_custom_prompt_file_also_gets_the_data_line(main_chat, tmp_path):
    custom = tmp_path / "prompt.txt"
    custom.write_text("Custom rules.", encoding="utf-8")
    client = FakeClient(["Hi."])
    main_chat(client, ["Hello"], "--prompt", str(custom))
    assert client.requests[0][1][0].content.startswith(f"Custom rules.\n\n{NAMES}\n\n")


def test_only_usable_names_are_listed(main_chat, tmp_path):
    folder = tmp_path / "data"
    folder.mkdir()
    for name in ("z.csv", "A.json", ".env", "csv.py", "evil.pyc"):
        (folder / name).write_text("1")
    (folder / "sub").mkdir()
    (folder / "link.csv").symlink_to(folder / "z.csv")
    client = FakeClient(["Hi."])
    main_chat(client, ["Hello"], data_dir=folder)
    system = client.requests[0][1][0].content
    assert "Data files available to run_python: A.json, z.csv." in system
    assert ".env" not in system and "csv.py" not in system and "link.csv" not in system


def test_data_line_kept_after_two_persona_switches_and_absent_on_resume_without_folder(
        main_chat, tmp_path):
    client = FakeClient(["One."], ["Two."], ["Three."])
    main_chat(client, ["Q1", "/persona analyse", "Q2", "/persona redaction", "Q3"])
    assert all(r[0].content.count(NAMES) == 1 for _, r in client.requests)
    resumed = FakeClient(["Back."])
    main_chat(resumed, ["Again"], "--session", "k7f2qa", data_dir=None)
    system = resumed.requests[0][1][0].content
    assert NAMES not in system and "The data folder" not in system


def test_resumed_self_correction_keeps_history_clean(main_chat, tmp_path, capsys):
    client = FakeClient(tool_call("1 / 0"), tool_call("print(4)"), ["Four."])
    main_chat(client, ["Compute it", "y", "y"])
    with StorageRepository(tmp_path / "s.db") as repository:
        messages = repository.for_creator("default").sessions.load("k7f2qa").messages
    assert [m.content.split(" · ")[0] for m in messages if m.content.startswith("Tool")] == [
        "Tool error from run_python:\nAttempt 1 of 3", "Tool result from run_python:\nAttempt 2 of 3"]
    assert messages[-1].content == "Four." and FIX_IT in messages[2].content
    capsys.readouterr()
    main_chat(FakeClient(), ["/history"], "--session", "k7f2qa")
    out = capsys.readouterr().out
    assert "1. Compute it" in out and "2." not in out and "Attempt" not in out


def test_ctrl_c_at_the_second_approval_through_main_saves_nothing(main_chat, tmp_path):
    client = FakeClient(tool_call("1 / 0"), tool_call("print(1)"))
    main_chat(client, ["Compute", "y", KeyboardInterrupt()])
    with StorageRepository(tmp_path / "s.db") as repository:
        assert repository.for_creator("default").sessions.load("k7f2qa") is None
    assert len(client.requests) == 2


def test_deadline_during_the_second_run_leaves_no_process_and_saves_nothing(tmp_path):
    marker = tmp_path / "pid"
    slow = (f"import os, time\nopen({str(marker)!r}, 'w').write(str(os.getpid()))\n"
            "time.sleep(100)\n")
    store = FakeSessionStore()
    client = FakeClient(tool_call("1 / 0"), tool_call(slow), ["never"])
    started = time.monotonic()
    output, session = chat(["Go"], client, Approval(True, True), operation_timeout=4,
                           recorder=SessionRecorder(store, "s1", title="t"))
    assert time.monotonic() - started < 15
    assert "Délai maximal dépassé" in output and store.sessions == {}
    assert len(session.messages) == 1
    with pytest.raises(ProcessLookupError):
        os.kill(int(marker.read_text()), 0)


# --- /run keeps T19's display ---------------------------------------------------------------

def test_run_command_keeps_the_t19_format(tmp_path):
    script = tmp_path / "big.py"
    script.write_text("print('a' + 'x' * 2998 + 'z')", encoding="utf-8")
    output, _ = chat([f"/run {script}"], FakeClient())
    assert FIX_IT not in output and "last 2000 characters" not in output
    assert "stdout:\na" + "x" * 2998 + "z" in output
