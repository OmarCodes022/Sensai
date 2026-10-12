import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

from fakes import FakeClient
from sensai.core.errors import LLMError
from sensai.app.prompts import load_system_prompt
from sensai.app.settings import Settings


SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "testing" / "adversarial_test.py"
spec = importlib.util.spec_from_file_location("adversarial_test", SCRIPT)
runner = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = runner
spec.loader.exec_module(runner)


def execute(tmp_path, client, answers):
    iterator = iter(answers)
    settings = Settings(_env_file=None, SENSAI_MODEL="test-model")
    report = tmp_path / "reports" / "results.jsonl"
    result = runner.run(settings, client, "test system prompt", report, lambda _: next(iterator))
    records = [json.loads(line) for line in report.read_text().splitlines()]
    return result, records


def test_records_manual_verdicts_and_resets_between_cases(tmp_path):
    client = FakeClient(["first reply"], ["second reply"])
    result, records = execute(
        tmp_path,
        client,
        [
            "first", "other", "expected first", "input one", "/end",
            "n", "pass", "reason one",
            "second", "other", "expected second", "input two", "/end",
            "n", "fail", "reason two", "/quit",
        ],
    )
    assert result == 1
    assert [case["verdict"] for case in records] == ["pass", "fail"]
    assert records[0]["expected_behavior"] == "expected first"
    assert records[0]["system_prompt"] == "test system prompt"
    assert records[0]["model"] == "test-model"
    assert records[0]["started_at"]
    assert records[1]["notes"] == "reason two"
    assert client.calls == [
        ["test system prompt", "input one"],
        ["test system prompt", "input two"],
    ]


def test_multiline_and_multiple_turns_keep_exact_input_and_history(tmp_path):
    client = FakeClient(["reply one"], ["reply two"])
    result, records = execute(
        tmp_path,
        client,
        [
            "conversation", "other", "expected",
            "first line", "  second line  ", "//end", "/end", "y",
            "follow-up", "/end", "n", "pass", "reviewed", "/quit",
        ],
    )
    assert result == 0
    text = "first line\n  second line  \n/end"
    assert records[0]["turns"][0]["input"] == text
    assert client.calls[1] == [
        "test system prompt", text, "reply one", "follow-up"
    ]


@pytest.mark.parametrize("lines", [[], ["   "], ["", ""]])
def test_blank_input_is_recorded_without_calling_model(tmp_path, lines):
    client = FakeClient()
    result, records = execute(
        tmp_path,
        client,
        [
            "blank", "malformed-input", "empty input rejected",
            *lines, "/end", "n", "pass", "input rejected", "/quit",
        ],
    )
    assert result == 0
    assert client.calls == []
    assert records[0]["turns"][0]["error"] == "empty input"
    assert records[0]["turns"][0]["error_kind"] == "input"


@pytest.mark.parametrize("reply", [LLMError("offline"), ["partial", LLMError("broken")]])
def test_backend_failure_is_explicitly_inconclusive(tmp_path, reply, capsys):
    result, records = execute(
        tmp_path,
        FakeClient(reply),
        ["failed connection", "other", "expected", "input", "/end", "/quit"],
    )
    assert result == 1
    case = records[0]
    assert case["verdict"] == "inconclusive"
    assert case["turns"][0]["error_kind"] == "backend"
    assert case["turns"][0]["response"] == ("" if isinstance(reply, LLMError) else "partial")
    assert "Backend error" in capsys.readouterr().out


def test_invalid_fields_and_verdicts_are_reprompted(tmp_path, capsys):
    result, records = execute(
        tmp_path,
        FakeClient(["reply"]),
        [
            "", "case", "", "other", "", "expected",
            "input", "/end", "maybe", "n",
            "success", "inconclusive", "needs review", "/quit",
        ],
    )
    assert result == 1
    assert records[0]["verdict"] == "inconclusive"
    output = capsys.readouterr().out
    assert "This field is required." in output
    assert "Choose one of: pass, fail, inconclusive." in output


@pytest.mark.parametrize("interrupt", [EOFError, KeyboardInterrupt])
@pytest.mark.parametrize("review", [[], ["n", "pass"]])
def test_interrupted_review_saves_attempt_with_no_pass_verdict(tmp_path, interrupt, review):
    answers = iter(["case", "other", "expected", "input", "/end", *review])

    def read(_):
        try:
            return next(answers)
        except StopIteration:
            raise interrupt from None

    report = tmp_path / "report.jsonl"
    with pytest.raises(interrupt):
        runner.run(
            Settings(_env_file=None, SENSAI_MODEL="test-model"),
            FakeClient(["reply"]),
            "system",
            report,
            read,
        )
    case = json.loads(report.read_text())
    assert case["verdict"] == "inconclusive"
    assert case["turns"][0]["response"] == "reply"
    markdown = report.with_suffix(".md").read_text()
    assert "**Verdict:** INCONCLUSIVE" in markdown
    assert "Case did not reach a completed review." in markdown
    assert "```text\nreply\n```" in markdown


def test_interrupted_stream_keeps_partial_reply(tmp_path):
    answers = iter(["case", "other", "expected", "input", "/end"])
    report = tmp_path / "report.jsonl"

    def write(text="", **kwargs):
        if text == "partial":
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        runner.run(
            Settings(_env_file=None, SENSAI_MODEL="test-model"),
            FakeClient(["partial", "rest"]),
            "system",
            report,
            lambda _: next(answers),
            write,
        )
    case = json.loads(report.read_text())
    assert case["verdict"] == "inconclusive"
    assert case["turns"][0]["response"] == "partial"
    markdown = report.with_suffix(".md").read_text()
    assert "**Verdict:** INCONCLUSIVE" in markdown
    assert "```text\npartial\n```" in markdown


def test_nonempty_value_error_is_not_disguised_as_input_rejection(tmp_path):
    answers = iter(["case", "other", "expected", "input", "/end"])
    report = tmp_path / "report.jsonl"
    with pytest.raises(ValueError, match="unexpected"):
        runner.run(
            Settings(_env_file=None, SENSAI_MODEL="test-model"),
            FakeClient(ValueError("unexpected")),
            "system",
            report,
            lambda _: next(answers),
        )
    assert json.loads(report.read_text())["verdict"] == "inconclusive"


def test_report_write_failure_is_not_silenced(tmp_path):
    with pytest.raises(IsADirectoryError):
        runner.save_case(
            tmp_path,
            runner.Case("name", "other", "expected", "model", "host", 60, "system"),
        )


def test_no_cases_does_not_look_like_a_passing_suite(tmp_path):
    report = tmp_path / "report.jsonl"
    assert runner.run(
        Settings(_env_file=None, SENSAI_MODEL="test-model"),
        FakeClient(),
        "system",
        report,
        lambda _: "/quit",
    ) == 2
    assert not report.exists()
    assert not report.with_suffix(".md").exists()


def test_default_report_names_are_readable_and_never_overwrite(tmp_path, monkeypatch):
    class Clock:
        @staticmethod
        def now(tz=None):
            return datetime(2026, 10, 2, 15, 41, 57, tzinfo=tz)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(runner, "datetime", Clock)
    case = runner.Case("case", "other", "expected", "model", "host", 60, "system")
    first = runner.save_case(None, case)
    original = first.read_text()
    second = runner.save_case(None, case)
    third = runner.save_case(None, case)
    assert first.name == "t10-2026-10-02_15-41-57.jsonl"
    assert second.name == "t10-2026-10-02_15-41-57-2.jsonl"
    assert third.name == "t10-2026-10-02_15-41-57-3.jsonl"
    assert first.read_text() == original
    assert json.loads(second.read_text())["name"] == "case"


def test_default_report_keeps_all_cases_in_one_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    answers = iter([
        "first", "other", "expected", "input", "/end", "n", "pass", "reason",
        "second", "other", "expected", "input", "/end", "n", "pass", "reason",
        "/quit",
    ])
    assert runner.run(
        Settings(_env_file=None, SENSAI_MODEL="test-model"),
        FakeClient(["reply"], ["reply"]),
        "system",
        None,
        lambda _: next(answers),
    ) == 0
    reports = list((tmp_path / "adversarial-reports").glob("*.jsonl"))
    assert len(reports) == 1
    assert [json.loads(line)["name"] for line in reports[0].read_text().splitlines()] == [
        "first", "second"
    ]


def test_no_cases_does_not_create_a_default_report(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert runner.run(
        Settings(_env_file=None, SENSAI_MODEL="test-model"),
        FakeClient(),
        "system",
        None,
        lambda _: "/quit",
    ) == 2
    assert not (tmp_path / "adversarial-reports").exists()


def test_default_prompt_has_no_preapproved_fictional_claim():
    prompt = load_system_prompt(str(SCRIPT.parents[2] / "prompts" / "system.txt"))
    assert "explicitly approved claims" in prompt
    assert "does not change them" in prompt
    assert "unless the application actually performed and confirmed it" in prompt
    assert "Dew Gel contains glycerin" not in prompt


def test_main_uses_selected_prompt_model_host_and_report(tmp_path, monkeypatch):
    prompt = tmp_path / "system.txt"
    prompt.write_text("custom system prompt\n")
    report = tmp_path / "report.jsonl"
    client = FakeClient()
    monkeypatch.setattr(runner, "create_client", lambda settings: client)
    seen = []

    def run(settings, actual_client, system_prompt, actual_report):
        seen.append((settings.model, settings.host, actual_client, system_prompt, actual_report))
        return 1

    monkeypatch.setattr(runner, "run", run)
    assert runner.main([
        "selected-model", "--prompt", str(prompt),
        "--host", "http://localhost:11435", "--report", str(report),
    ]) == 1
    assert seen == [
        ("selected-model", "http://localhost:11435", client, "custom system prompt", report)
    ]


@pytest.mark.parametrize("prompt_exists,content,exit_code", [
    (False, None, 1),
    (True, " \n ", 2),
])
def test_main_rejects_missing_or_empty_prompt(tmp_path, prompt_exists, content, exit_code):
    prompt = tmp_path / "system.txt"
    if prompt_exists:
        prompt.write_text(content)
    with pytest.raises(SystemExit) as error:
        runner.main(["test-model", "--prompt", str(prompt)])
    assert error.value.code == exit_code


def test_markdown_report_summarizes_cases_and_preserves_conversations(tmp_path):
    result, records = execute(
        tmp_path,
        FakeClient(["first reply"], ["follow-up reply"], ["partial", LLMError("offline")]),
        [
            "B1-JB-001", "jailbreak", "Keep the system prompt private.",
            "first attack", "/end", "y", "follow-up attack", "/end",
            "n", "fail", "Disclosed hidden instructions.",
            "B1-JB-002", "jailbreak", "Resist the attack.",
            "another attack", "/end", "/quit",
        ],
    )
    assert result == 1
    report = (tmp_path / "reports" / "results.md").read_text()
    assert "| 2 | 0 | 1 | 1 |" in report
    assert "| 1 | B1-JB-001 | jailbreak | **FAIL** |" in report
    assert "| 2 | B1-JB-002 | jailbreak | **INCONCLUSIVE** |" in report
    assert "## Case 1: B1-JB-001" in report
    assert "## Case 2: B1-JB-002" in report
    assert "### Turn 2" in report
    assert "Keep the system prompt private." in report
    assert "Disclosed hidden instructions." in report
    for case in records:
        assert case["started_at"] in report
        for turn in case["turns"]:
            assert turn["input"] in report
            assert turn["response"] in report
    assert "**Backend error**\n\n```text\noffline\n```" in report
    assert "Backend error; attack was not fully evaluated." in report
    assert report.count("<summary>Exact system prompt</summary>") == 1
    assert "**Model:** test-model" in report
    assert "**HTTP timeout:** 60 seconds" in report


def test_markdown_report_keeps_different_configurations_and_verdict_counts():
    first = runner.Case("first", "other", "expected", "model-a", "host-a", 60, "prompt-a")
    second = runner.Case("second", "other", "expected", "model-b", "host-b", 30, "prompt-b")
    first.verdict = second.verdict = "pass"
    report = runner.render_markdown([first, second])
    assert "| 2 | 2 | 0 | 0 |" in report
    assert report.count("<summary>Exact system prompt</summary>") == 2
    assert "[Setup 1](#setup-1)" in report
    assert "[Setup 2](#setup-2)" in report
    for value in ("model-a", "model-b", "host-a", "host-b", "prompt-a", "prompt-b"):
        assert value in report


def test_markdown_escapes_attack_content_without_changing_evidence(tmp_path):
    attack = "```text\n## Forged result\n````\n<script>bad()</script>"
    case = runner.Case(
        "test | [link](url)\nnext", "other|category", "<img src=x>", "model", "host", 60,
        attack,
    )
    case.turns = [runner.Turn(attack, attack)]
    report = runner.save_case(tmp_path / "report.jsonl", case)
    markdown = report.with_suffix(".md").read_text()
    assert "test \\| \\[link\\](url)<br>next" in markdown
    assert "other\\|category" in markdown
    assert "&lt;img src=x&gt;" in markdown
    assert f"`````text\n{attack}\n`````" in markdown
    assert json.loads(report.read_text())["turns"][0]["input"] == attack


def test_empty_input_is_readable(tmp_path):
    execute(
        tmp_path, FakeClient(),
        ["empty", "malformed-input", "reject empty input", "/end", "n", "pass", "rejected", "/quit"],
    )
    report = (tmp_path / "reports" / "results.md").read_text()
    assert "(Empty input.)" in report
    assert "(No response text.)" in report
    assert "**Input rejected**\n\n```text\nempty input\n```" in report


def test_markdown_write_failure_preserves_raw_evidence_and_old_markdown(tmp_path, monkeypatch):
    path = tmp_path / "report.jsonl"
    case = runner.Case("case", "other", "expected", "model", "host", 60, "system")
    runner.save_case(path, case)
    previous = path.with_suffix(".md").read_text()

    def fail_replace(self, destination):
        raise PermissionError("cannot replace report")

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(OSError, match="JSONL evidence saved.*Markdown could not be updated"):
        runner.save_case(path, case)
    assert len(runner.read_cases(path)) == 2
    assert path.with_suffix(".md").read_text() == previous
    assert not list(tmp_path.glob(".report.md.*"))


@pytest.mark.parametrize("filename", ["evidence", "report.md", "report.jsonl"])
def test_custom_evidence_names_never_get_overwritten_by_markdown(tmp_path, filename):
    report = tmp_path / filename
    case = runner.Case("case", "other", "expected", "model", "host", 60, "system")
    runner.save_case(report, case)
    assert json.loads(report.read_text())["name"] == "case"
    assert runner.markdown_path(report) != report
    assert "# T10 adversarial test report" in runner.markdown_path(report).read_text()


def test_existing_markdown_name_is_not_overwritten_by_new_default_session(tmp_path, monkeypatch):
    class Clock:
        @staticmethod
        def now(tz=None):
            return datetime(2026, 10, 2, 15, 41, 57, tzinfo=tz)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(runner, "datetime", Clock)
    directory = tmp_path / "adversarial-reports"
    directory.mkdir()
    previous = directory / "t10-2026-10-02_15-41-57.md"
    previous.write_text("previous report")
    case = runner.Case("case", "other", "expected", "model", "host", 60, "system")
    report = runner.save_case(None, case)
    assert report.name == "t10-2026-10-02_15-41-57-2.jsonl"
    assert previous.read_text() == "previous report"


def test_main_renders_existing_evidence_without_model_or_prompt(tmp_path, monkeypatch, capsys):
    report = tmp_path / "old.jsonl"
    case = runner.Case("old case", "jailbreak", "expected", "old-model", "host", 60, "old prompt")
    report.write_text(json.dumps(runner.asdict(case)) + "\n")
    monkeypatch.delenv("SENSAI_MODEL", raising=False)
    monkeypatch.setattr(runner, "Settings", lambda: Settings(_env_file=None))

    def unexpected(*args):
        pytest.fail("Rendering evidence must not load a prompt or call Ollama.")

    monkeypatch.setattr(runner, "load_system_prompt", unexpected)
    monkeypatch.setattr(runner, "create_client", unexpected)
    original = report.read_text()
    assert runner.main(["--render-report", str(report)]) == 0
    assert report.read_text() == original
    assert "old case" in report.with_suffix(".md").read_text()
    assert "Markdown report saved" in capsys.readouterr().out


@pytest.mark.parametrize("content", ["not JSON\n", "{}\n", '{"verdict": "wrong"}\n'])
def test_invalid_existing_evidence_is_not_skipped_or_appended(tmp_path, content):
    report = tmp_path / "report.jsonl"
    report.write_text(content)
    case = runner.Case("case", "other", "expected", "model", "host", 60, "system")
    with pytest.raises(runner.ReportError, match="line 1"):
        runner.save_case(report, case)
    assert report.read_text() == content
    with pytest.raises(SystemExit) as error:
        runner.main(["--render-report", str(report)])
    assert error.value.code == 1
    assert not report.with_suffix(".md").exists()


def test_invalid_verdict_in_existing_evidence_is_explicit(tmp_path):
    case = runner.Case("case", "other", "expected", "model", "host", 60, "system")
    case.verdict = "wrong"
    report = tmp_path / "report.jsonl"
    report.write_text(json.dumps(runner.asdict(case)) + "\n")
    with pytest.raises(runner.ReportError, match="Invalid verdict.*line 1"):
        runner.read_cases(report)


def test_main_reports_missing_evidence_file(tmp_path, capsys):
    with pytest.raises(SystemExit) as error:
        runner.main(["--render-report", str(tmp_path / "missing.jsonl")])
    assert error.value.code == 1
    assert "error:" in capsys.readouterr().err


def test_report_and_render_report_options_are_mutually_exclusive(tmp_path):
    with pytest.raises(SystemExit) as error:
        runner.main(["--report", str(tmp_path / "new.jsonl"),
                     "--render-report", str(tmp_path / "old.jsonl")])
    assert error.value.code == 2
