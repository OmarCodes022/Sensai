"""T21 sandbox edge cases: report boundaries, adversarial summaries, the permission hook."""

from functools import partial
import os
import random
import signal
import tempfile

import pytest

from permission_ports import AllowAll, Interrupting
from sandbox_handlers import FAST
from sensai import sandbox
from sensai.cli.approval import sanitize
from sensai.core.ports import PermissionDecision, ToolCall
from sensai.sandbox import (FIX_IT, MODEL_CHARS, SandboxError, SandboxLimits, SandboxRun,
                            data_file_names, model_report, python_tool, report_summary, run_python)
from sensai.tools import ToolRegistry

LIST = "import os\nprint(sorted(n for n in os.listdir() if n != 'main.py'))"


@pytest.fixture(autouse=True)
def temp_root(tmp_path, monkeypatch):
    root = tmp_path / "temp-root"
    root.mkdir()
    monkeypatch.setenv("TMPDIR", str(root))
    monkeypatch.setattr(tempfile, "tempdir", str(root))
    yield root
    assert not [p for p in root.iterdir() if p.name.startswith(sandbox.PREFIX)]


def run(stdout="", stderr="", exit_code=0, timed_out=False, truncated=False, denied=()):
    return SandboxRun(stdout, stderr, exit_code, .25, timed_out, truncated, denied)


class Port:
    def __init__(self, decide=lambda request: PermissionDecision(True)):
        self.decide = decide
        self.requests = []

    def check(self, request):
        self.requests.append(request)
        return self.decide(request)


# --- model_report boundaries ----------------------------------------------------------

@pytest.mark.parametrize("label", ["stdout", "stderr"])
@pytest.mark.parametrize("size, cut", [(MODEL_CHARS - 1, False), (MODEL_CHARS, False),
                                       (MODEL_CHARS + 1, True)])
def test_cut_starts_at_one_more_than_the_limit(label, size, cut):
    text = "a" + "x" * (size - 2) + "z" if size > 1 else "z"
    streams = {"stdout": text + "\n\n", "stderr": ""} if label == "stdout" else {
        "stdout": "", "stderr": text + "\n"}
    lines = model_report(run(**streams, exit_code=1)).split("\n")
    expected_label = f"{label} (last {MODEL_CHARS} characters):" if cut else f"{label}:"
    assert lines[1:] == ([ "(output truncated)"] if cut else []) + [
        expected_label, text[-MODEL_CHARS:], FIX_IT]
    assert len(lines[-2]) == min(size, MODEL_CHARS)


@pytest.mark.parametrize("char", ["é", "€", "😀", "\u0301"])
def test_cut_counts_characters_not_bytes(char):
    lines = model_report(run(char * (MODEL_CHARS + 5))).split("\n")
    assert lines[1:3] == ["(output truncated)", f"stdout (last {MODEL_CHARS} characters):"]
    assert lines[3] == char * MODEL_CHARS


def test_only_stderr_on_success_and_both_streams_cut_independently():
    assert model_report(run("", "DeprecationWarning: x\n")) == (
        f"Exit code 0 · 0.2 s\nstderr:\nDeprecationWarning: x\n{FIX_IT}")
    lines = model_report(run("o" * 3000, "short\n", 1)).split("\n")
    assert lines[2] == f"stdout (last {MODEL_CHARS} characters):" and lines[4:6] == ["stderr:", "short"]


@pytest.mark.parametrize("stdout, stderr", [("\n", ""), ("", "\n\n"), ("\n\n", "\n")])
def test_newline_only_streams_are_omitted(stdout, stderr):
    assert model_report(run(stdout, stderr)) == f"Exit code 0 · 0.2 s\n{FIX_IT}"


def test_capture_truncated_without_a_model_cut_keeps_plain_labels():
    assert model_report(run("12\n", truncated=True)) == (
        f"Exit code 0 · 0.2 s\n(output truncated)\nstdout:\n12\n{FIX_IT}")


def test_limit_lines_use_the_given_limits_and_come_before_truncation():
    limits = SandboxLimits(wall_seconds=2.5, file_bytes=3 * 1024 * 1024)
    assert model_report(run(exit_code=-9, timed_out=True, truncated=True), limits).split("\n")[1:3] == [
        "Time limit reached (2.5 s)", "(output truncated)"]
    assert model_report(run(exit_code=-signal.SIGXFSZ), limits).split("\n")[1] == (
        "File size limit reached (3 MB)")
    assert model_report(run(exit_code=-signal.SIGTERM)).split("\n")[1] == "Killed by signal SIGTERM"


def test_denied_line_sits_right_before_the_fix_it_line_even_with_cut_streams():
    lines = model_report(run("o" * 3000, "e" * 3000, 1, truncated=True, denied=("a.csv",))).split("\n")
    assert lines[-2:] == ["Not available (not allowed): a.csv", FIX_IT]
    assert lines.count("(output truncated)") == 1


def test_fix_it_line_is_last_even_when_the_output_ends_with_it():
    text = model_report(run(f"{FIX_IT}\n", f"{FIX_IT}\n", 1))
    assert text.endswith(f"stderr:\n{FIX_IT}\n{FIX_IT}")


# --- report_summary on adversarial text -----------------------------------------------

@pytest.mark.parametrize("result, detail", [
    # ANSI colour codes, carriage-return progress bars and odd line breaks.
    (run("", "\x1b[31mKeyError: 'x'\x1b[0m\n", 1), "\x1b[31mKeyError: 'x'\x1b[0m"),
    (run("10%\r50%\r100%\n"), "100%"),
    (run("a\u2028b\x85c\n"), "c"),
    (run("ok\n   \n\t\n"), "ok"),
    (run("", "x" * 10_000, 1), "x" * MODEL_CHARS),
    # A fake status or fix-it line inside the output does not break the parse.
    (run("Exit code 1 · 9.9 s\n42\n"), "42"),
    (run("", f"{FIX_IT}\nboom\n", 1), "boom"),
    # On failure only the stderr stream is used, never stdout.
    (run("stdout tail\n", "", 2), None),
    (run("", "", 1, denied=("a.csv",)), None),
])
def test_report_summary_adversarial(result, detail):
    text = model_report(result)
    assert report_summary(text) == (text.split("\n")[0], detail)


def test_report_summary_never_raises_and_its_display_is_one_printable_line():
    pieces = ["stdout:", "stderr:", "stderr (last 2000 characters):", FIX_IT, "Exit code 0 · 1 s",
              "Exit code -1 · 1 s", "Not available (not allowed): x", "(output truncated)", "",
              " ", "\r", "\x1b[2J", "\u202e", "\ud800", "\x00", "\x85", "trace", "é" * 300, "\n"]
    rng = random.Random(21)
    for _ in range(3000):
        text = "\n".join(rng.choice(pieces) for _ in range(rng.randrange(0, 9)))
        if rng.random() < .5:
            text = model_report(run(text, rng.choice(pieces) * 3, rng.choice([0, 1, -9])))
        first, detail = report_summary(text)
        assert isinstance(first, str) and len(first.splitlines()) <= 1
        assert detail is None or (detail.strip() and len(detail.splitlines()) == 1)
        for shown in (sanitize(first), sanitize(detail or "")[:160]):
            assert shown.isprintable()


# --- permission hook -------------------------------------------------------------------

@pytest.fixture
def mixed(tmp_path):
    """Every kind of entry run_python must filter, plus names that sort non-trivially."""
    folder = tmp_path / "mixed"
    folder.mkdir()
    for name in ("b.csv", "a.csv", "C.CSV", "with space.txt", "données.json", "main.PY.bak",
                 ".env", ".hidden.csv", "csv.py", "evil.PYC", "mod.so", "x.pyw", "y.pyd"):
        (folder / name).write_text(name)
    (folder / "sub").mkdir()
    (folder / "sub" / "inner.csv").write_text("1")
    (folder / "link.csv").symlink_to(folder / "a.csv")
    (folder / "dirlink").symlink_to(folder / "sub")
    os.mkfifo(folder / "pipe.csv")
    return folder


VISIBLE = ["C.CSV", "a.csv", "b.csv", "données.json", "main.PY.bak", "with space.txt"]


def test_names_listed_always_match_the_files_copied(mixed):
    assert data_file_names(mixed) == VISIBLE
    assert eval(run_python(LIST, mixed, limits=FAST).stdout) == VISIBLE
    refuse = Port(lambda request: PermissionDecision(not request.resource.endswith(".csv")))
    names = data_file_names(mixed, refuse)
    result = run_python(LIST, mixed, limits=FAST, permission=refuse)
    assert names == eval(result.stdout) == ["C.CSV", "données.json", "main.PY.bak", "with space.txt"]
    assert result.denied == ("a.csv", "b.csv")


def test_port_is_asked_once_per_visible_file_with_its_absolute_path(mixed, monkeypatch):
    monkeypatch.chdir(mixed.parent)
    port = Port()
    run_python("pass", "mixed", limits=FAST, permission=port)
    assert [r.resource for r in port.requests] == [str(mixed / n) for n in VISIBLE]
    assert {r.action for r in port.requests} == {"read"}


def test_denied_names_are_sorted_whatever_order_the_port_refuses_in(tmp_path):
    folder = tmp_path / "d"
    folder.mkdir()
    for name in ("zeta.csv", "Alpha.csv", "beta.csv", "keep.txt"):
        (folder / name).write_text("1")
    result = run_python(LIST, folder, limits=FAST, permission=Port(
        lambda request: PermissionDecision(request.resource.endswith(".txt"))))
    assert result.denied == ("Alpha.csv", "beta.csv", "zeta.csv")
    assert model_report(result).split("\n")[-2] == (
        "Not available (not allowed): Alpha.csv, beta.csv, zeta.csv")


@pytest.mark.parametrize("answer", [None, PermissionDecision(False, "policy"), True,
                                    PermissionDecision("True")])
def test_odd_answers_fail_closed(tmp_path, answer):
    folder = tmp_path / "d"
    folder.mkdir()
    (folder / "a.csv").write_text("1")
    assert data_file_names(folder, Port(lambda request: answer)) == []
    assert run_python(LIST, folder, limits=FAST, permission=Port(lambda r: answer)).denied == ("a.csv",)


def test_keyboard_interrupt_from_the_port_propagates_before_any_folder_or_process(tmp_path):
    folder = tmp_path / "d"
    folder.mkdir()
    (folder / "a.csv").write_text("1")
    marker = tmp_path / "ran"
    with pytest.raises(KeyboardInterrupt):
        run_python(f"open({str(marker)!r}, 'w')", folder, permission=Interrupting(), limits=FAST)
    with pytest.raises(KeyboardInterrupt):
        data_file_names(folder, Interrupting())
    assert not marker.exists()


def test_interrupting_port_in_the_tool_worker_gives_an_error_and_runs_nothing(tmp_path):
    folder = tmp_path / "d"
    folder.mkdir()
    (folder / "a.csv").write_text("1")
    marker = tmp_path / "ran"
    registry = ToolRegistry()
    registry.register(sandbox.RUN_PYTHON, partial(python_tool, data_dir=str(folder),
                                                  permission=Interrupting(), limits=FAST))
    result = registry.execute(ToolCall("run_python", {"code": f"open({str(marker)!r}, 'w')"}))
    assert result.error is not None and not marker.exists()


def test_permission_none_and_allow_all_copy_the_same_files(mixed):
    assert run_python(LIST, mixed, limits=FAST).stdout == run_python(
        LIST, mixed, limits=FAST, permission=AllowAll()).stdout


def test_data_file_names_skips_the_size_check_but_the_run_reports_it(tmp_path):
    folder = tmp_path / "big"
    folder.mkdir()
    with open(folder / "huge.csv", "wb") as handle:
        handle.truncate(51 * 1024 * 1024)  # Sparse: no real disk use.
    assert data_file_names(folder) == ["huge.csv"]
    result = python_tool({"code": "print(1)"}, data_dir=folder, limits=FAST)
    assert result.error == "data folder is larger than 50 MB"


def test_data_file_names_of_an_empty_or_filtered_folder(tmp_path):
    folder = tmp_path / "e"
    folder.mkdir()
    assert data_file_names(folder) == []
    (folder / ".env").write_text("x")
    (folder / "csv.py").write_text("x")
    assert data_file_names(str(folder)) == []


# --- real runs through python_tool -----------------------------------------------------

def tool(code, **options):
    return python_tool({"code": code}, limits=FAST, **options)


def test_wall_time_limit_is_an_error_report():
    result = tool("import time\ntime.sleep(30)")
    lines = result.error.split("\n")
    assert result.output == result.error
    assert lines[0].startswith("Exit code -9 · ") and lines[1] == "Time limit reached (1.5 s)"
    assert lines[-1] == FIX_IT and report_summary(result.error)[1] is None


def test_cpu_limit_is_an_error_report():
    result = tool("while True:\n    pass")
    assert result.error is not None
    assert "CPU time limit reached" in result.error.split("\n")[1:3]


def test_capture_cut_and_model_cut_together():
    result = tool("print('x' * 50_000)")
    lines = result.output.split("\n")
    assert result.error is None
    # Only the first 10,000 characters are captured: the slice is not the end of the output.
    assert lines[1:3] == ["(output truncated)", "stdout (characters 8001-10000; the rest was not captured):"]
    assert lines[3] == "x" * MODEL_CHARS


def test_multibyte_output_keeps_the_last_characters():
    result = tool("print('é' * 2500 + 'FIN')")
    assert result.output.split("\n")[3] == ("é" * 2500 + "FIN")[-MODEL_CHARS:]


def test_long_traceback_keeps_its_last_line():
    result = tool("print('noise\\n' * 3000)\nimport sys\nsys.stderr.write('w' * 9000 + '\\n')\n"
                  "raise KeyError('engaged')")
    assert report_summary(result.error)[1] == "KeyError: 'engaged'"
    assert result.error.split("\n")[-2] == "KeyError: 'engaged'"


def test_warning_on_success_is_not_an_error():
    result = tool("import sys\nsys.stderr.write('careful\\n')")
    assert result.error is None and report_summary(result.output) == (
        result.output.split("\n")[0], None)


def test_exit_code_without_output_is_an_error_with_no_detail():
    result = tool("raise SystemExit(3)")
    assert result.error.startswith("Exit code 3 · ") and report_summary(result.error)[1] is None
