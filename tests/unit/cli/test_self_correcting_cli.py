"""T21 CLI: the model fixes its run_python code from the errors, within 3 attempts per question."""

import json
import os
from pathlib import Path
import tempfile
import time

import pytest

from fakes import FakeClient, scripted_terminal
from sensai.chat.session import ChatSession
from sensai.chat import saved_sessions
from sensai.chat.personas import PersonaRegistry
from sensai.cli import main as cli
from sensai.core.ports import ApprovalDecision
from sensai.memory.sqlite_store import StorageRepository
from sensai.sandbox import FIX_IT, PREFIX

pytestmark = pytest.mark.usefixtures("isolated_settings")
FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
NAMES = "Data files available to run_python: brand.json, dms.json, engagement.csv, posts.json."
WRONG = 'import csv\nrows = list(csv.DictReader(open("engagement.csv")))\nprint(rows[0]["engaged"])\n'
RIGHT = """\
import csv
rows = [r for r in csv.DictReader(open("engagement.csv"))
        if r["source"] == "instagram_insights_daily" and "2026-09-21" <= r["date"] <= "2026-09-27"]
print(round(sum(float(r["engagement_rate"]) for r in rows) / len(rows), 1))
"""
STOP = ("Stopped after 3 attempts: answer with the last result or error, "
        "without calling run_python again.")


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
        self.requests.append(json.loads(request.resource)["code"])
        return ApprovalDecision(self.answers.pop(0))


def tool_call(code):
    return [json.dumps({"tool": "run_python", "arguments": {"code": code}})]


def chat(inputs, client, approval, data_dir=str(FIXTURES), **options):
    session = ChatSession(client, "model", "sys")
    lines = []
    reads = iter([*inputs, "exit"])
    registry = cli._tools(lambda prompt: pytest.fail("plain reader used"), approval=approval,
                          data_dir=data_dir)
    cli.repl(session, read=lambda prompt: next(reads), tool_registry=registry,
             write=lambda *args, **kwargs: lines.append(" ".join(map(str, args))), **options)
    return "\n".join(lines), session


def sent(client):
    return [request[-1].content for _, request in client.requests[1:]]


def test_failed_run_goes_back_and_the_fix_is_approved_again():
    client = FakeClient(tool_call(WRONG), tool_call(RIGHT),
                        ["The average daily engagement rate ", "was 11.7%."])
    approval = Approval(True, True)
    output, session = chat(["Average engagement rate from 21 to 27 Sep?"], client, approval)
    assert approval.requests == [WRONG, RIGHT]
    first, second = sent(client)[:2]
    assert first.startswith("Tool error from run_python:\nAttempt 1 of 3 · Exit code 1 · ")
    assert "KeyError: 'engaged'" in first and first.endswith(FIX_IT)
    assert second.startswith("Tool result from run_python:\nAttempt 2 of 3 · Exit code 0 · ")
    assert second.endswith(f"stdout:\n11.7\n{FIX_IT}")
    lines = output.split("\n")
    run1 = next(i for i, line in enumerate(lines) if "Run 1" in line)
    assert lines[run1].startswith("Using tool: run_python · Run 1 · Exit code 1 · ")
    assert lines[run1 + 1] == "KeyError: 'engaged'"
    assert lines[run1 + 2].startswith("Using tool: run_python · Run 2 · Exit code 0 · ")
    assert lines[run1 + 3] == "11.7"
    # The answer is streamed chunk by chunk after the runs.
    assert lines[run1 + 4:run1 + 6] == ["The average daily engagement rate ", "was 11.7%."]
    assert "Attempt" not in output and FIX_IT not in output
    assert session.messages[-1].content == "The average daily engagement rate was 11.7%."


def test_fourth_call_is_stopped_and_the_chat_continues():
    client = FakeClient(*[tool_call(f"raise ValueError('try {n}')") for n in (1, 2, 3)],
                        tool_call("print(1)"), ["It failed: ValueError: try 3."], ["Still here"])
    approval = Approval(True, True, True)
    output, session = chat(["Compute", "Next"], client, approval)
    assert len(approval.requests) == 3
    messages = sent(client)
    assert [m.split(" · ")[0] for m in messages[:3]] == [
        f"Tool error from run_python:\nAttempt {n} of 3" for n in (1, 2, 3)]
    assert messages[3] == f"Tool error from run_python:\n{STOP}"
    assert [line for line in output.split("\n") if line.startswith("Using tool")][3] == (
        "Using tool: run_python · Stopped after 3 attempts")
    assert "ValueError: try 3" in output and "It failed: ValueError: try 3." in output
    assert session.messages[-1].content == "Still here"
    assert messages[-1] == "Next"


def test_attempts_reset_with_each_question():
    client = FakeClient(tool_call("print(1)"), ["one"], tool_call("print(2)"), ["two"])
    output, _ = chat(["Q1", "Q2"], client, Approval(True, True))
    assert [m.split(" · ")[0] for m in sent(client) if m.startswith("Tool")] == [
        "Tool result from run_python:\nAttempt 1 of 3"] * 2
    assert output.count("Using tool: run_python · Run 1 · Exit code 0 · ") == 2


def test_refusal_runs_nothing(tmp_path):
    marker = tmp_path / "ran"
    client = FakeClient(tool_call(f"open({str(marker)!r}, 'w').write('x')"), ["Not run."])
    output, _ = chat(["Compute"], client, Approval(False))
    assert not marker.exists()
    assert sent(client)[0] == "Tool error from run_python:\nAttempt 1 of 3 · tool approval refused"
    lines = output.split("\n")
    index = lines.index("Using tool: run_python · Run 1 · tool approval refused")
    assert lines[index + 1] == "Not run."


def test_question_without_computation_asks_nothing():
    client = FakeClient(["Hello Nadia."])
    approval = Approval()
    output, _ = chat(["Hi"], client, approval)
    assert approval.requests == [] and "Using tool" not in output and "Hello Nadia." in output


def test_ctrl_c_during_the_fix_run_stops_the_loop(tmp_path):
    marker = tmp_path / "pid"
    slow = (f"import os, time\nopen({str(marker)!r}, 'w').write(str(os.getpid()))\n"
            "time.sleep(100)\n")
    client = FakeClient(tool_call("1 / 0"), tool_call(slow), ["never"])
    started = time.monotonic()
    output, session = chat(["Go"], client, Approval(True, True),
                           cancel_requested=lambda: marker.exists() and marker.read_text() != "")
    assert time.monotonic() - started < 10
    assert "Run 1 · Exit code 1" in output and "Réponse interrompue" in output
    with pytest.raises(ProcessLookupError):
        os.kill(int(marker.read_text()), 0)
    assert len(session.messages) == 1 and len(client.requests) == 2


# --- through cli.main: data file names, persona switch, resume, saved session ------

@pytest.fixture
def main_chat(monkeypatch, tmp_path):
    monkeypatch.setattr(saved_sessions, "new_session_id", lambda exists: "k7f2qa")

    def run(client, inputs, *argv, data_dir=FIXTURES):
        if data_dir is not None:
            monkeypatch.setenv("SENSAI_DATA_DIR", str(data_dir))
        monkeypatch.setattr(cli, "create_client", lambda settings: client)
        monkeypatch.setattr(cli, "TerminalInput", scripted_terminal([*inputs, "exit"]))
        cli.main(["model", "--db", str(tmp_path / "s.db"), *argv])
    return run


def saved(tmp_path):
    with StorageRepository(tmp_path / "s.db") as repository:
        return [m.content for m in repository.for_creator("default").sessions.load("k7f2qa").messages]


def test_names_in_prompt_survive_persona_and_resume_with_code_results_and_answer_saved(
        main_chat, tmp_path):
    client = FakeClient(tool_call(WRONG), tool_call(RIGHT), ["It was 11.7%."], ["Noted."])
    main_chat(client, ["Average engagement rate?", "y", "y", "/persona analyse", "Thanks"])
    system = [request[0].content for _, request in client.requests]
    assert len(system) == 4 and all(NAMES in prompt for prompt in system)
    assert "fix the code and run it again" in system[0]
    analyse = PersonaRegistry.from_file(None).get("analyse").system_prompt
    assert analyse not in system[0] and analyse in system[-1]
    messages = saved(tmp_path)
    assert messages[0] == "Average engagement rate?"
    assert json.loads(messages[1])["arguments"]["code"] == WRONG
    assert messages[2].startswith("Tool error from run_python:\nAttempt 1 of 3 · Exit code 1")
    assert json.loads(messages[3])["arguments"]["code"] == RIGHT
    assert "stdout:\n11.7\n" in messages[4] and messages[5] == "It was 11.7%."

    resumed = FakeClient(["Back."])
    main_chat(resumed, ["Again"], "--session", "k7f2qa")
    [(_, request)] = resumed.requests
    assert NAMES in request[0].content and analyse in request[0].content
    assert [m.content for m in request[1:]] == [*messages, "Again"]


def test_empty_data_folder_is_announced(main_chat, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / ".env").write_text("SECRET=1")
    client = FakeClient(["Hi."])
    main_chat(client, ["Hello"], data_dir=empty)
    prompt = client.requests[0][1][0].content
    assert "The data folder has no files run_python can use." in prompt and NAMES not in prompt


def test_no_data_folder_adds_nothing(main_chat):
    client = FakeClient(["Hi."])
    main_chat(client, ["Hello"], data_dir=None)
    prompt = client.requests[0][1][0].content
    assert "Data files available" not in prompt and "The data folder" not in prompt


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads any folder")
def test_unreadable_data_folder_stops_before_the_client(monkeypatch, tmp_path):
    locked = tmp_path / "locked"
    locked.mkdir(mode=0)
    monkeypatch.setenv("SENSAI_DATA_DIR", str(locked))
    monkeypatch.setattr(cli, "create_client", lambda settings: pytest.fail("client created"))
    monkeypatch.setattr(cli, "TerminalInput", scripted_terminal(None))
    try:
        with pytest.raises(SystemExit, match="^error: cannot read data folder: "):
            cli.main(["model", "--db", str(tmp_path / "s.db")])
    finally:
        locked.chmod(0o755)
