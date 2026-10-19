import importlib.util
import sys
from datetime import datetime
from pathlib import Path

import pytest
import requests

from fakes import FakeClient
from sensai.core.errors import LLMError
from sensai.llm.ollama_api import OllamaUsage, UsageError
from sensai.settings import Settings


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "evals" / "prompt_compare" / "compare.py"
spec = importlib.util.spec_from_file_location("prompt_compare", SCRIPT)
compare = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = compare
spec.loader.exec_module(compare)


class UsageClient(FakeClient):
    """FakeClient that reports one scripted usage per request, like OllamaClient."""

    def __init__(self, sink, usages, *replies):
        super().__init__(*replies)
        self.sink = sink
        self.usages = list(usages)

    def stream(self, model, messages, cancellation=None):
        usage = self.usages.pop(0)
        try:
            yield from super().stream(model, messages, cancellation)
        finally:
            self.sink(usage)


def usage(latency, prompt=None, output=None, error=None):
    return OllamaUsage(prompt_tokens=prompt, output_tokens=output,
                       latency_ms=latency, error=error)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("network access in an offline test")

    monkeypatch.setattr(requests, "post", refuse)
    for name in ("SENSAI_MODEL", "SENSAI_TIMEOUT", "SENSAI_CONTEXT_LENGTH", "OLLAMA_HOST"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(compare, "Settings", lambda: Settings(_env_file=None))


def prompt(text, path="p.txt"):
    return compare.Prompt(path, text, "abc123", text.count("\n") + 1)


def write(path, text):
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_read_questions_skips_blank_and_comment_lines(tmp_path):
    path = tmp_path / "q.txt"
    write(path, "# header\n\nfirst?\n  second?  \n# skip\n")
    assert compare.read_questions(path) == ["first?", "second?"]


def test_default_questions_and_original_version_exist():
    assert len(compare.read_questions(compare.DEFAULT_QUESTIONS)) == 6
    original = SCRIPT.parent / "versions" / "2026-10-20-original.txt"
    packaged = ROOT / "src" / "sensai" / "chat" / "system_prompt.txt"
    assert original.read_bytes() == packaged.read_bytes()


def test_same_questions_in_order_to_both_prompts_with_fresh_messages():
    client = FakeClient(["a1"], ["b1"], ["a2"], ["b2"])
    results = compare.run_comparison(
        client, "m", [prompt("SYS A"), prompt("SYS B")], ["q1", "q2"]
    )
    assert client.calls == [["SYS A", "q1"], ["SYS B", "q1"], ["SYS A", "q2"], ["SYS B", "q2"]]
    assert [request[1][0].role for request in client.requests] == ["system"] * 4
    assert [request[1][1].role for request in client.requests] == ["user"] * 4
    assert {request[0] for request in client.requests} == {"m"}
    assert [[answer.text for answer in row] for row in results] == [["a1", "b1"], ["a2", "b2"]]


def test_failed_call_is_recorded_and_run_continues():
    recorder = compare.UsageRecorder()
    client = UsageClient(
        recorder,
        [usage(100, 10, 5), usage(50, error=UsageError.TIMEOUT), usage(300, 20, 7),
         usage(200, 30, 9)],
        ["ok ", "A"], ["partial", LLMError("Ollama timed out")], ["A2"], ["B2"],
    )
    results = compare.run_comparison(
        client, "m", [prompt("A"), prompt("B")], ["q1", "q2"], recorder
    )
    failed = results[0][1]
    assert failed.error == "Ollama timed out"
    assert failed.text == "partial"
    assert failed.usage.error == UsageError.TIMEOUT
    assert results[0][0].text == "ok A" and results[0][0].usage.latency_ms == 100
    assert results[1][1].text == "B2" and results[1][1].usage.output_tokens == 9


def test_report_summary_and_per_question_numbers():
    recorder = compare.UsageRecorder()
    client = UsageClient(
        recorder,
        [usage(100, 10, 5), usage(50, error=UsageError.TIMEOUT), usage(300, 20, 7),
         usage(200, 30, 9)],
        ["A1"], LLMError("boom"), ["A2"], ["B2"],
    )
    prompts = [prompt("A", "v/a.txt"), prompt("B", "v/b.txt")]
    results = compare.run_comparison(client, "m", prompts, ["q1", "q2"], recorder)
    report = compare.render_report("m", "http://h", "q.txt", prompts, ["q1", "q2"],
                                   results, datetime(2026, 10, 20, 12, 0, 0))
    assert "| A | 2 | 0 | 200 ms | 30 | 12 |" in report
    assert "| B | 1 | 1 | 200 ms | 30 | 9 |" in report
    assert "vary between runs" in report
    assert "2026-10-20T12:00:00" in report and "v/a.txt" in report and "abc123" in report
    assert "Latency: 100 ms, prompt tokens: 10, output tokens: 5" in report
    assert "Latency: 50 ms, prompt tokens: n/a, output tokens: n/a" in report
    assert "**Error**" in report and "boom" in report
    assert report.index("## Question 1") < report.index("## Question 2")


def test_report_renders_answers_and_paths_safely():
    answers = [[compare.Answer(text="```\n# not a heading\n<script>"), compare.Answer()]]
    report = compare.render_report("m|x", "h", "q*.txt", [prompt("A", "a_|b.txt"), prompt("B")],
                                   ["q `x`"], answers, datetime(2026, 10, 20))
    assert "````text\n```\n# not a heading\n<script>\n````" in report
    assert "a\\_\\|b.txt" in report and "m\\|x" in report and "q\\*.txt" in report
    assert "(No answer text.)" in report


def test_main_writes_default_report_under_prompt_reports(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    a = write(tmp_path / "a.txt", "Prompt A\n")
    b = write(tmp_path / "b.txt", "Prompt B\n")
    questions = write(tmp_path / "q.txt", "q1\n")
    created = []

    def factory(host, timeout, usage_sink=None, context_length=None):
        created.append((host, timeout, context_length))
        return UsageClient(usage_sink, [usage(10, 1, 1), usage(20, 2, 2)], ["x"], ["y"])

    monkeypatch.setattr(compare, "OllamaClient", factory)
    assert compare.main([a, b, "--model", "m", "--questions", questions]) == 0
    reports = list((tmp_path / "prompt-reports").glob("compare-*.md"))
    assert len(reports) == 1
    assert str(Path("prompt-reports") / reports[0].name) in capsys.readouterr().out
    assert created == [("http://localhost:11434", 60.0, None)]


def test_main_exit_1_when_every_call_fails(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    a = write(tmp_path / "a.txt", "A")
    questions = write(tmp_path / "q.txt", "q1\n")
    monkeypatch.setattr(compare, "OllamaClient",
                        lambda *args, **kwargs: FakeClient(LLMError("x"), LLMError("y")))
    output = tmp_path / "out" / "r.md"
    assert compare.main([a, a, "--model", "m", "--questions", questions,
                         "--output", str(output)]) == 1
    assert output.read_text().count("**Error**") == 2


@pytest.mark.parametrize("case", ["no-model", "missing-prompt", "empty-prompt",
                                  "missing-questions", "empty-questions"])
def test_main_exit_2_on_bad_input(tmp_path, monkeypatch, case):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(compare, "OllamaClient", lambda *args, **kwargs: FakeClient())
    a = write(tmp_path / "a.txt", "A")
    b = write(tmp_path / "b.txt", "  \n" if case == "empty-prompt" else "B")
    questions = write(tmp_path / "q.txt", "# only\n" if case == "empty-questions" else "q\n")
    if case == "missing-prompt":
        b = str(tmp_path / "missing.txt")
    if case == "missing-questions":
        questions = str(tmp_path / "missing-q.txt")
    argv = [a, b, "--questions", questions]
    if case != "no-model":
        argv += ["--model", "m"]
    with pytest.raises(SystemExit) as exit_info:
        compare.main(argv)
    assert exit_info.value.code == 2
    assert not (tmp_path / "prompt-reports").exists()
