import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

from fakes import FakeClient
from sensai.errors import LLMError
from sensai.prompts import load_system_prompt
from sensai.settings import Settings


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "adversarial_test.py"
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
    prompt = load_system_prompt(str(SCRIPT.parents[1] / "prompts" / "system.txt"))
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
