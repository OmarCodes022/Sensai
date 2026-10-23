"""T19 CLI, adversarial: what the model receives, approval display, Ctrl+C leftovers."""

from functools import partial
import json
import os
from pathlib import Path
import signal
import tempfile
import time

import pytest

from fakes import FakeClient
from sandbox_handlers import fast_python_tool
from sensai.chat.session import ChatSession
from sensai.cli import main as cli
from sensai.cli.approval import TerminalApproval
from sensai.core.ports import ApprovalDecision, ApprovalRequest
from sensai.sandbox import PREFIX, RUN_PYTHON
from sensai.tools import ToolRegistry

pytestmark = pytest.mark.usefixtures("isolated_settings")


@pytest.fixture(autouse=True)
def temp_root(tmp_path, monkeypatch):
    root = tmp_path / "temp-root"
    root.mkdir()
    monkeypatch.setenv("TMPDIR", str(root))
    monkeypatch.setattr(tempfile, "tempdir", str(root))
    yield root
    assert not [p for p in root.iterdir() if p.name.startswith(PREFIX)]


def gone(pid, wait=3.0):
    end = time.monotonic() + wait
    while True:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        try:
            if Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] == "Z":
                return True
        except (OSError, IndexError):
            pass
        if time.monotonic() > end:
            return False
        time.sleep(.05)


def reap(*pids):
    alive = [pid for pid in pids if not gone(pid)]
    for pid in alive:
        os.kill(pid, signal.SIGKILL)
    return alive


def spawner(marker):
    return "\n".join([
        "import os, subprocess, sys, time",
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(100)'])",
        f"open({str(marker)!r} + '.tmp', 'w').write(f'{{os.getpid()}} {{child.pid}} {{os.getcwd()}}')",
        f"os.rename({str(marker)!r} + '.tmp', {str(marker)!r})",
        "time.sleep(100)", ""])


def read_marker(marker):
    pid, grandchild, folder = marker.read_text().split(" ", 2)
    return int(pid), int(grandchild), folder


class Approval:
    def __init__(self, answer):
        self.answer = answer
        self.requests = []

    def request(self, request):
        self.requests.append(request)
        return ApprovalDecision(self.answer)


class Keys:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.prompts = []

    def __call__(self, prompt, choices, default):
        self.prompts.append((prompt, choices))
        answer = self.answers.pop(0)
        if isinstance(answer, type):
            raise answer
        return answer or default


def tool_call(code, **extra):
    return json.dumps({"tool": "run_python", "arguments": {**extra, "code": code}})


def chat(inputs, client=None, **options):
    client = client or FakeClient()
    session = ChatSession(client, "model", "sys")
    lines = []
    reads = iter([*inputs, "exit"])
    cli.repl(session, read=lambda prompt: next(reads),
             write=lambda *args, **kwargs: lines.append(" ".join(map(str, args))), **options)
    return "\n".join(lines), session, client


def fast_registry(data_dir=None):
    registry = ToolRegistry()
    registry.register(RUN_PYTHON, partial(fast_python_tool, data_dir=data_dir))
    return registry


def sent_to_model(code, registry=None):
    client = FakeClient([tool_call(code)], ["ok"])
    output, _, _ = chat(["Go"], client, tool_registry=registry or fast_registry())
    return client.requests[1][1][-1].content, output


# --- error vs output, as the model receives it ---------------------------------------

def test_model_gets_time_limit_as_tool_error():
    sent, output = sent_to_model("import time\ntime.sleep(100)")
    assert sent.startswith("Tool error from run_python:\nExit code -9 · ")
    assert "time limit reached" in sent.lower()
    assert "Using tool: run_python · Exit code -9 · " in output


def test_model_gets_cpu_limit_as_tool_error():
    sent, _ = sent_to_model("while True: pass")
    assert sent.startswith("Tool error from run_python:\n") and "CPU time limit reached" in sent


def test_model_gets_success_with_warnings_as_result_including_stderr():
    sent, _ = sent_to_model("import sys\nprint('42')\nprint('careful', file=sys.stderr)")
    assert sent.startswith("Tool result from run_python:\nExit code 0 · ")
    assert sent.endswith("stdout:\n42\nstderr:\ncareful")


def test_model_gets_bounded_text_for_huge_output_with_traceback():
    code = "print('x' * 10_000_000)\nimport sys\nsys.stderr.write('e' * 10_000_000)\n{}['reach']"
    sent, _ = sent_to_model(code)
    assert sent.startswith("Tool error from run_python:\nExit code 1 · ")
    assert "(output truncated)" in sent and sent.endswith("KeyError: 'reach'")
    assert len(sent) < 21_000


def test_model_gets_data_folder_problem_as_error_when_folder_vanishes(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    registry = cli._tools(None, approval=Approval(True), data_dir=str(data))
    data.rmdir()
    sent, output = sent_to_model("print(1)", registry)
    assert sent == f"Tool error from run_python:\ndata folder not found: {data}"
    assert f"Using tool: run_python · data folder not found: {data}" in output


# --- Ctrl+C through the real worker -------------------------------------------------

def test_ctrl_c_during_model_run_kills_code_grandchild_and_folder(tmp_path):
    marker = tmp_path / "pids"
    client = FakeClient([tool_call(spawner(marker))], ["never"])
    registry = cli._tools(None, approval=Approval(True))
    started = time.monotonic()
    output, session, _ = chat(["Go"], client, tool_registry=registry, cancel_requested=marker.exists)
    assert time.monotonic() - started < 10
    pid, grandchild, folder = read_marker(marker)
    assert reap(pid, grandchild) == []
    assert "Réponse interrompue" in output and not os.path.exists(folder)
    assert len(session.messages) == 1 and len(client.requests) == 1


def test_ctrl_c_during_run_command_kills_grandchild_and_folder(tmp_path):
    marker = tmp_path / "pids"
    script = tmp_path / "slow script.py"
    script.write_text(spawner(marker), encoding="utf-8")
    output, session, client = chat([f"/run {script}", "/tools"], cancel_requested=marker.exists)
    pid, grandchild, folder = read_marker(marker)
    assert reap(pid, grandchild) == []
    assert "Exécution interrompue" in output and not os.path.exists(folder)
    assert "run_python: " in output.split("Exécution interrompue")[1]
    assert client.requests == [] and len(session.messages) == 1


# --- approval through the real registry ---------------------------------------------

def approve_with(keys, code, client_reply=None, **extra):
    lines = []
    approval = TerminalApproval(keys, lines.append)
    registry = cli._tools(None, approval=approval)
    client = FakeClient([tool_call(code, **extra)], [client_reply or "Answer"])
    output, session, _ = chat(["Go"], client, tool_registry=registry)
    return lines, client.requests[1][1][-1].content, output


def test_refusal_with_preview_runs_nothing_and_tells_the_model(tmp_path):
    marker = tmp_path / "ran"
    code = f"open({str(marker)!r}, 'w').write('x')\n" + "\n".join(f"x{i} = {i}" for i in range(20))
    lines, sent, output = approve_with(Keys("n"), code)
    assert sent == "Tool error from run_python:\ntool approval refused" and not marker.exists()
    assert lines[1] == "Run run_python?" and lines[-1] == "    … (+15 more lines)"
    assert "x19 = 19" not in "\n".join(lines)
    assert "Using tool: run_python · tool approval refused" in output


def test_view_all_shows_every_line_then_run(tmp_path):
    marker = tmp_path / "ran"
    code = "\n".join(f"x{i} = {i}" for i in range(20)) + f"\nopen({str(marker)!r}, 'w').write('x')"
    keys = Keys("v", "y")
    lines, sent, _ = approve_with(keys, code)
    assert [p for p, _ in keys.prompts] == ["[y] run · [n] refuse · [v] view all ", "[y] run · [n] refuse "]
    assert "    x19 = 19" in lines and marker.exists()
    assert sent.startswith("Tool result from run_python:\nExit code 0 · ")


def test_ctrl_c_at_the_approval_prompt_runs_nothing(tmp_path):
    marker = tmp_path / "ran"
    lines = []
    approval = TerminalApproval(Keys(KeyboardInterrupt), lines.append)
    client = FakeClient([tool_call(f"open({str(marker)!r}, 'w').write('x')")])
    output, session, _ = chat(["Go"], client, tool_registry=cli._tools(None, approval=approval))
    assert "Réponse interrompue" in output and not marker.exists() and len(session.messages) == 1


def test_terminal_escapes_in_model_code_are_shown_escaped():
    code = "print(1)  \x1b[2K\x1b[1A# looks harmless\r# \u202eevil\x9b31m\x07"
    lines, _, _ = approve_with(Keys("n"), code)
    shown = "\n".join(lines)
    for raw in ("\x1b", "\x9b", "\x07", "\u202e", "\r"):
        assert raw not in shown
    assert "\\x1b[2K" in shown and "\\x0d" in shown and "\\u202e" in shown


def test_extra_argument_key_cannot_fake_extra_preview_lines():
    fake = "\n".join(["note:", "    print('hello')"] + ["    pass"] * 40)
    lines, sent, _ = approve_with(Keys("n"), "import shutil; shutil.rmtree('/')", **{fake: 0})
    physical = "\n".join(lines[2:]).split("\n")
    # 6 argument lines + one header + the hidden-lines note at most.
    assert len(physical) <= 6 + 1 + 1, physical


def test_lone_surrogate_in_code_still_shows_the_approval_prompt():
    def terminal(line=""):
        line.encode("utf-8")  # What print() does on a UTF-8 terminal (errors="strict").
        printed.append(line)

    printed = []
    approval = TerminalApproval(Keys("n"), terminal)
    client = FakeClient(['{"tool": "run_python", "arguments": {"code": "print(\'\\ud83d\')"}}'],
                        ["Answer"])
    output, _, _ = chat(["Go"], client, tool_registry=cli._tools(None, approval=approval))
    assert "Please type something." not in output and len(client.requests) == 2
    assert client.requests[1][1][-1].content == "Tool error from run_python:\ntool approval refused"
    assert any("\\ud83d" in line for line in printed)


def test_approval_request_carries_the_exact_code():
    approval = Approval(False)
    code = "print('é\\n')\n\ttab"
    client = FakeClient([tool_call(code)], ["Answer"])
    chat(["Go"], client, tool_registry=cli._tools(None, approval=approval))
    [request] = approval.requests
    assert isinstance(request, ApprovalRequest) and json.loads(request.resource) == {"code": code}
    assert request.action == "run_python" and request.reason == RUN_PYTHON.description


def test_run_command_ignores_approval_and_history(tmp_path):
    script = tmp_path / "x.py"
    script.write_text("print('direct')", encoding="utf-8")
    approval = Approval(False)
    output, session, client = chat([f"/run {script}"], tool_registry=cli._tools(None, approval=approval))
    assert "stdout:\ndirect" in output and approval.requests == [] and len(session.messages) == 1
