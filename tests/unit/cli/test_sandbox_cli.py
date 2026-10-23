"""T19 CLI wiring: run_python in /tools and the tool loop, /run, SENSAI_DATA_DIR."""

import json
import os
from pathlib import Path
import tempfile

import pytest

from fakes import FakeClient, scripted_terminal
from sensai.chat.session import ChatSession
from sensai.cli import main as cli
from sensai.core.ports import ApprovalDecision
from sensai.sandbox import PREFIX
from sensai.settings import Settings

pytestmark = pytest.mark.usefixtures("isolated_settings")
FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
AVERAGE = """\
import csv
rows = [r for r in csv.DictReader(open("engagement.csv"))
        if r["source"] == "instagram_insights_daily" and "2026-09-21" <= r["date"] <= "2026-09-27"]
print(round(sum(int(r["accounts_reached"]) for r in rows) / len(rows), 1))
"""


@pytest.fixture(autouse=True)
def temp_root(tmp_path, monkeypatch):
    root = tmp_path / "temp-root"
    root.mkdir()
    monkeypatch.setenv("TMPDIR", str(root))
    monkeypatch.setattr(tempfile, "tempdir", str(root))
    yield root
    assert not [p for p in root.iterdir() if p.name.startswith(PREFIX)]


class Approval:
    def __init__(self, answer):
        self.answer = answer
        self.requests = []

    def request(self, request):
        self.requests.append(request)
        return ApprovalDecision(self.answer)


class Recorder:
    def __getattr__(self, name):
        raise AssertionError(f"recorder.{name} must not be used by /run")


def tool_call(code):
    return json.dumps({"tool": "run_python", "arguments": {"code": code}})


def chat(inputs, client=None, **options):
    """Run the REPL on scripted input; return (output lines, session, client)."""
    client = client or FakeClient()
    session = ChatSession(client, "model", "sys")
    lines = []
    reads = iter([*inputs, "exit"])
    cli.repl(session, read=lambda prompt: next(reads),
             write=lambda *args, **kwargs: lines.append(" ".join(map(str, args))), **options)
    return "\n".join(lines), session, client


def test_tools_command_lists_run_python():
    output, _, client = chat(["/tools"])
    assert "run_python: Run Python 3 code" in output and "calculate:" in output
    assert client.requests == []


def test_run_prints_result_without_model_history_or_recorder(tmp_path):
    script = tmp_path / "ok.py"
    script.write_text("print('hello from the sandbox')", encoding="utf-8")
    output, session, client = chat([f"/run {script}"], recorder=Recorder())
    assert "Running in the sandbox (limit 15 s)…" in output
    assert "Exit code 0 · " in output and "stdout:\nhello from the sandbox" in output
    assert client.requests == [] and len(session.messages) == 1


def test_run_traceback_then_chat_continues(tmp_path):
    script = tmp_path / "broken.py"
    script.write_text("rows = {}\nprint(rows['reach'])\n", encoding="utf-8")
    output, session, client = chat([f"/run {script}", "Next"], FakeClient(["Still here"]))
    assert 'File "main.py", line 2' in output and "KeyError: 'reach'" in output
    assert "Exit code 1 · " in output and "Still here" in output
    assert [m.content for m in session.messages[1:]] == ["Next", "Still here"]


def test_run_computes_from_engagement_csv(tmp_path):
    script = tmp_path / "average.py"
    script.write_text(AVERAGE, encoding="utf-8")
    output, _, _ = chat([f"/run {script}"], data_dir=str(FIXTURES))
    assert "stdout:\n1021.4" in output


@pytest.mark.parametrize("make, message", [
    (None, "usage: /run <file.py>"),
    (lambda path: None, "No such file or directory"),
    (lambda path: path.mkdir(), "is not a regular file"),
    (lambda path: os.mkfifo(path), "is not a regular file"),
    (lambda path: path.write_bytes(b"#" * (1024 * 1024 + 1)), "is larger than 1 MiB"),
    (lambda path: path.write_bytes(b"print('\xff')"), "is not UTF-8 text"),
])
def test_run_input_errors(tmp_path, make, message):
    path = tmp_path / "script.py"
    if make is not None:
        make(path)
    output, _, _ = chat(["/run" if make is None else f"/run {path}"])
    assert message in output and "Running in the sandbox" not in output


@pytest.mark.skipif(not os.path.isdir("/proc/self/fd"), reason="needs /proc")
def test_rejected_scripts_do_not_leak_file_descriptors(tmp_path):
    folder = tmp_path / "folder"
    folder.mkdir()
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    before = len(os.listdir("/proc/self/fd"))
    for _ in range(50):
        for path in (folder, fifo):
            with pytest.raises(ValueError, match="is not a regular file"):
                cli._read_script(str(path))
    assert len(os.listdir("/proc/self/fd")) == before


def test_run_strips_a_leading_bom(tmp_path):
    script = tmp_path / "bom.py"
    script.write_bytes("\ufeffprint('bom')\n1 / 0\n".encode("utf-8"))
    output, _, _ = chat([f"/run {script}"])
    assert "stdout:\nbom" in output and 'File "main.py", line 2' in output


def test_run_chat_exit_removes_stale_sandbox_folders(monkeypatch, temp_root):
    import subprocess
    import sys
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    stale = temp_root / f"{PREFIX}{dead.pid}-killed"
    (stale / "big").mkdir(parents=True)
    monkeypatch.setattr(cli, "create_client", lambda settings: FakeClient())
    monkeypatch.setattr(cli, "TerminalInput", scripted_terminal(["exit"]))
    cli.main(["model"])
    assert not stale.exists()


def test_run_ctrl_c_stops_the_code(tmp_path):
    marker = tmp_path / "pid"
    script = tmp_path / "slow.py"
    script.write_text(f"import os, time\nopen({str(marker)!r}, 'w').write(str(os.getpid()))\n"
                      "time.sleep(100)\n", encoding="utf-8")
    output, _, _ = chat([f"/run {script}"], cancel_requested=lambda: marker.exists()
                        and marker.read_text() != "")
    assert "Exécution interrompue" in output
    pid = int(marker.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


@pytest.mark.parametrize("approved", [True, False])
def test_model_call_needs_approval(tmp_path, approved):
    marker = tmp_path / "ran"
    approval = Approval(approved)
    code = f"open({str(marker)!r}, 'w').write('x')\nprint(6 * 7)"
    client = FakeClient([tool_call(code)], ["Answer"])
    registry = cli._tools(lambda prompt: pytest.fail("plain reader used"), approval=approval)
    output, session, _ = chat(["Compute"], client, tool_registry=registry)
    assert [(r.action, json.loads(r.resource)) for r in approval.requests] == [
        ("run_python", {"code": code})]
    sent = client.requests[1][1][-1].content
    if approved:
        assert sent.startswith("Tool result from run_python:\nExit code 0 · ")
        assert sent.endswith("stdout:\n42") and marker.exists()
        assert "Using tool: run_python · Exit code 0 · " in output
    else:
        assert sent == "Tool error from run_python:\ntool approval refused"
        assert not marker.exists()
        assert "Using tool: run_python · tool approval refused" in output
    assert code not in output and session.messages[-1].content == "Answer"


def test_failed_code_is_sent_to_model_as_error():
    client = FakeClient([tool_call("1 / 0")], ["Fixed"])
    registry = cli._tools(None, approval=Approval(True))
    output, _, _ = chat(["Compute"], client, tool_registry=registry)
    sent = client.requests[1][1][-1].content
    assert sent.startswith("Tool error from run_python:\nExit code 1 · ")
    assert "ZeroDivisionError" in sent
    assert "Using tool: run_python · Exit code 1 · " in output


def test_main_asks_with_single_key_approval_and_uses_data_dir(monkeypatch, capsys):
    monkeypatch.setenv("SENSAI_DATA_DIR", str(FIXTURES))
    client = FakeClient([tool_call(AVERAGE)], ["The average was 1021.4."])
    monkeypatch.setattr(cli, "create_client", lambda settings: client)
    monkeypatch.setattr(cli, "TerminalInput", scripted_terminal(["Average reach?", "y", "exit"]))
    cli.main(["model"])
    output = capsys.readouterr().out
    assert "Run run_python?" in output and "    rows = [r for r in csv.DictReader" in output
    assert client.requests[1][1][-1].content.endswith("stdout:\n1021.4")


@pytest.mark.parametrize("kind", ["missing", "file"])
def test_invalid_data_dir_fails_before_client(monkeypatch, tmp_path, kind):
    path = tmp_path / "data"
    if kind == "file":
        path.write_text("x")
    monkeypatch.setenv("SENSAI_DATA_DIR", str(path))
    monkeypatch.setattr(cli, "create_client", lambda settings: pytest.fail("client created"))
    monkeypatch.setattr(cli, "TerminalInput", scripted_terminal(None))
    with pytest.raises(SystemExit, match="data folder not found"):
        cli.main(["model"])


def test_empty_data_dir_means_unset(monkeypatch):
    monkeypatch.setenv("SENSAI_DATA_DIR", "")
    assert cli.parse_args(Settings(_env_file=None), ["model"]).data_dir is None
    monkeypatch.setenv("SENSAI_DATA_DIR", str(FIXTURES))
    assert cli.parse_args(Settings(_env_file=None), ["model"]).data_dir == str(FIXTURES)


def test_second_ctrl_c_during_cleanup_stays_in_the_repl(monkeypatch):
    from sensai.core.cancellation import OperationCancelled

    def interrupted():
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "remove_stale_folders", interrupted)
    output, session, _ = chat(["Q1", "Q2"], FakeClient([OperationCancelled("stop")], ["A2"]))
    assert "Réponse interrompue" in output and session.messages[-1].content == "A2"
