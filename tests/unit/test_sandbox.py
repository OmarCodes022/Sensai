"""T19 sandbox: real child interpreters, small limits, temp folders under tmp_path."""

from functools import partial
import json
import os
from pathlib import Path
import pickle
import signal
import subprocess
import sys
import tempfile
import textwrap
import time

import pytest

from sensai import sandbox
from sensai.core.cancellation import CancellationToken, OperationCancelled, OperationTimedOut
from sensai.core.ports import ToolCall, ToolResult
from sensai.sandbox import (PREFIX, RUN_PYTHON, SandboxError, SandboxLimits, SandboxRun,
                            format_run, python_tool, run_python)
from sensai.tools import ToolRegistry

FAST = SandboxLimits(wall_seconds=1.5)
SRC = str(Path(sandbox.__file__).resolve().parents[1])
LINUX = sys.platform.startswith("linux")


@pytest.fixture(autouse=True)
def temp_root(tmp_path, monkeypatch):
    """Sandbox folders (also in spawned workers) live under a private temp root."""
    root = tmp_path / "temp-root"
    root.mkdir()
    monkeypatch.setenv("TMPDIR", str(root))
    monkeypatch.setattr(tempfile, "tempdir", str(root))
    return root


def sandboxes(root):
    return sorted(p.name for p in root.iterdir() if p.name.startswith(PREFIX))


def gone(pid, wait=3.0):
    """True once pid no longer exists (a zombie left to init counts as gone)."""
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


def spawner(marker, then="time.sleep(100)"):
    """Code that starts a grandchild, records pids and folder, then runs `then`."""
    return textwrap.dedent(f"""\
        import os, subprocess, sys, time
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(100)"])
        with open({str(marker)!r} + ".tmp", "w") as f:
            f.write(f"{{os.getpid()}} {{child.pid}} {{os.getcwd()}}")
        os.rename({str(marker)!r} + ".tmp", {str(marker)!r})
        {then}
        """)


def read_marker(marker):
    pid, grandchild, folder = marker.read_text().split(" ", 2)
    return int(pid), int(grandchild), folder


def test_success_prints_and_cleans_up(tmp_path, temp_root):
    marker = tmp_path / "cwd"
    run = run_python(f"import os\nopen({str(marker)!r}, 'w').write(os.getcwd())\nprint('hello')",
                     limits=FAST)
    assert run.exit_code == 0 and not run.timed_out and not run.truncated
    assert run.stdout == "hello\n"
    folder = marker.read_text()
    assert Path(folder).name.startswith(f"{PREFIX}{os.getpid()}-")
    assert not os.path.exists(folder) and sandboxes(temp_root) == []
    assert format_run(run, FAST).startswith("Exit code 0 · ")
    result = python_tool({"code": "print(6 * 7)"})
    assert result.error is None and result.output.endswith(f"stdout:\n42\n{sandbox.FIX_IT}")


def test_exception_reports_traceback_line_and_error_text(temp_root):
    result = python_tool({"code": "x = 1\n\nprint(x / 0)\n"})
    assert result.output.startswith("Exit code 1 · ")
    assert 'File "main.py", line 3' in result.output and "ZeroDivisionError" in result.output
    assert result.error == result.output
    assert sandboxes(temp_root) == []


def test_temp_folder_path_is_hidden_from_output():
    run = run_python("import os, sys\nprint(os.path.abspath('data.csv'), os.getcwd())\n"
                     "print(os.path.abspath('x'), file=sys.stderr)\nraise KeyError('reach')\n")
    assert run.stdout == "data.csv .\n"
    assert 'File "main.py", line 4, in <module>' in run.stderr
    assert run.stderr.startswith("x\n") and PREFIX not in run.stdout + run.stderr


def test_temp_folder_path_is_hidden_when_tmpdir_is_a_symlink(tmp_path, temp_root, monkeypatch):
    link = tmp_path / "tmp-link"
    link.symlink_to(temp_root)
    monkeypatch.setattr(tempfile, "tempdir", str(link))
    run = run_python("import os\nprint(os.getcwd(), os.path.abspath('a'))\n1 / 0\n")
    assert run.stdout == ". a\n" and 'File "main.py", line 3' in run.stderr
    assert str(link) not in run.stderr and PREFIX not in run.stdout + run.stderr
    assert sandboxes(temp_root) == []


@pytest.mark.parametrize("cookie, hidden", [
    ("utf-7", "# +AAo-open(MARKER, 'w').write('x')"),
    ("unicode_escape", "# \\nopen(MARKER, 'w').write('x')"),
    ("raw_unicode_escape", "# \\u000aopen(MARKER, 'w').write('x')"),
])
def test_coding_cookie_cannot_run_what_the_preview_shows_as_a_comment(tmp_path, cookie, hidden):
    marker = tmp_path / "ran"
    code = f"# coding: {cookie}\nprint('shown')\n" + hidden.replace("MARKER", repr(str(marker))) + "\n"
    run = run_python(code, limits=FAST)
    assert run.exit_code == 1 and "SyntaxError" in run.stderr
    assert not marker.exists() and "shown" not in run.stdout


def test_utf8_cookie_and_leading_bom_still_run_with_correct_lines():
    run = run_python("# coding: utf-8\nprint('é')\nraise ValueError('line 3')\n", limits=FAST)
    assert run.stdout == "é\n" and 'File "main.py", line 3' in run.stderr
    run = run_python("\ufeffprint('bom')\n1 / 0\n", limits=FAST)
    assert run.stdout == "bom\n" and 'File "main.py", line 2' in run.stderr


def test_exit_after_the_wall_deadline_is_not_a_timeout(monkeypatch):
    collect = sandbox._collect

    def late(process, limits, token, guard):
        output, _ = collect(process, limits, token, guard)
        process.wait()
        return output, True  # The deadline passed just as the code exited by itself.

    monkeypatch.setattr(sandbox, "_collect", late)
    run = run_python("print('done')", limits=FAST)
    assert run.exit_code == 0 and not run.timed_out


@pytest.mark.parametrize("code", ["while True: pass", "import time\ntime.sleep(100)"])
def test_wall_limit_stops_code(code, temp_root):
    started = time.monotonic()
    run = run_python(code, limits=SandboxLimits(wall_seconds=1))
    assert time.monotonic() - started < 3
    assert run.timed_out and run.exit_code == -signal.SIGKILL
    assert "time limit reached (1 s)" in format_run(run, SandboxLimits(wall_seconds=1)).lower()
    assert sandboxes(temp_root) == []


def test_cpu_limit_is_reported():
    limits = SandboxLimits(wall_seconds=10, cpu_seconds=1)
    run = run_python("while True: pass", limits=limits)
    assert run.exit_code == -signal.SIGXCPU and not run.timed_out
    assert "CPU time limit reached" in format_run(run, limits)


def test_output_is_capped_head_of_stdout_and_tail_of_stderr(monkeypatch):
    sizes = []

    class Recording(sandbox._Output):
        def add(self, name, data):
            super().add(name, data)
            sizes.append(max(len(self.out), len(self.err)))

    monkeypatch.setattr(sandbox, "_Output", Recording)
    limits = SandboxLimits(wall_seconds=10, output_chars=100)
    code = ("import sys\nprint('START' + 'x' * 10_000_000)\n"
            "sys.stderr.write('e' * 5_000_000 + 'END')")
    run = run_python(code, limits=limits)
    assert run.exit_code == 0 and run.truncated
    assert len(run.stdout) == 100 and run.stdout.startswith("START")
    assert len(run.stderr) == 100 and run.stderr.endswith("END")
    assert max(sizes) <= 400
    assert "(output truncated)" in format_run(run, limits)


def test_long_multibyte_output_is_cut_by_characters():
    run = run_python("print('é' * 50)", limits=SandboxLimits(output_chars=10))
    assert run.stdout == "é" * 10 and run.truncated


@pytest.mark.skipif(not LINUX, reason="RLIMIT_AS is only enforced on Linux")
def test_memory_limit_fails_the_code_not_sensai():
    limits = SandboxLimits(memory_bytes=256 * 1024 * 1024)
    run = run_python("data = bytearray(1024 ** 3)\nprint(len(data))", limits=limits)
    assert run.exit_code != 0 and "MemoryError" in run.stderr


def test_file_size_limit_is_reported():
    limits = SandboxLimits(file_bytes=1024 * 1024)
    run = run_python("open('big.bin', 'wb').write(b'x' * 2 * 1024 * 1024)", limits=limits)
    assert run.exit_code != 0
    assert "File size limit reached (1 MB)" in format_run(run, limits)


def test_environment_holds_only_the_allowed_values(monkeypatch):
    for name in ("SENSAI_X", "OLLAMA_X", "API_KEY"):
        monkeypatch.setenv(name, "secret-value")
    run = run_python("import json, os\nprint(json.dumps({**os.environ, 'cwd': os.getcwd()}))")
    env = json.loads(run.stdout)
    folder = env.pop("cwd")
    if sys.platform == "darwin":
        env.pop("__CF_USER_TEXT_ENCODING", None)  # Added by macOS itself; harmless.
    assert env == {"PATH": os.defpath, "LANG": "C.UTF-8", "PYTHONIOENCODING": "utf-8",
                   "PYTHONDONTWRITEBYTECODE": "1", "HOME": folder, "TMPDIR": folder}
    assert "secret-value" not in run.stdout


def test_data_folder_copies_top_level_regular_files_only(tmp_path):
    data = tmp_path / "data"
    (data / "nested").mkdir(parents=True)
    (data / "b.csv").write_text("b")
    (data / "a.txt").write_text("a")
    (data / "main.py").write_text("print('data file must not replace the code')")
    (data / "nested" / "c.txt").write_text("c")
    (data / ".env").write_text("API_KEY=secret")
    for name in ("csv.py", "json.pyc", "x.pyw", "m.so", "m.pyd", "STAT.PY"):
        (data / name).write_text("raise SystemExit('a data file shadowed the stdlib')")
    (tmp_path / "outside.txt").write_text("secret")
    (data / "link.txt").symlink_to(tmp_path / "outside.txt")
    code = "import csv, json, os, stat\nprint(sorted(os.listdir()), open('a.txt').read())"
    run = run_python(code, data)
    assert run.stdout.strip() == "['a.txt', 'b.csv', 'main.py'] a"


def test_data_folder_skips_hidden_files_like_dotenv(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    (data / ".env").write_text("OPENAI_API_KEY=leak-me")
    (data / ".hidden.csv").write_text("x")
    (data / "visible.csv").write_text("ok")
    monkeypatch.chdir(data)  # SENSAI_DATA_DIR=.
    run = run_python("import os\nprint(sorted(os.listdir()))", ".", limits=FAST)
    assert run.stdout == "['main.py', 'visible.csv']\n"


def test_data_folder_size_ignores_skipped_files(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / ".big").write_bytes(b"x" * 50)
    (data / "big.py").write_bytes(b"x" * 50)
    (data / "small.csv").write_bytes(b"x" * 5)
    run = run_python("print(open('small.csv').read())", data, limits=SandboxLimits(data_bytes=10))
    assert run.stdout == "xxxxx\n"


def test_data_folder_errors_happen_before_any_run(tmp_path, temp_root):
    data = tmp_path / "data"
    data.mkdir()
    (data / "big.csv").write_bytes(b"x" * 20)
    with pytest.raises(SandboxError, match="larger than"):
        run_python("print(1)", data, limits=SandboxLimits(data_bytes=10))
    with pytest.raises(SandboxError, match="data folder not found"):
        run_python("print(1)", tmp_path / "missing")
    assert python_tool({"code": "print(1)"}, data_dir=str(data / "big.csv")) == ToolResult(
        "", f"data folder not found: {data / 'big.csv'}")
    assert sandboxes(temp_root) == []


def test_data_file_growing_after_listing_is_still_capped(tmp_path, monkeypatch, temp_root):
    data = tmp_path / "data"
    data.mkdir()
    (data / "grow.csv").write_bytes(b"x" * 5)
    listed = sandbox._data_files(data, 10)
    (data / "grow.csv").write_bytes(b"x" * 50)
    monkeypatch.setattr(sandbox, "_data_files", lambda *args: listed)
    with pytest.raises(SandboxError, match="larger than"):
        run_python("print(1)", data, limits=SandboxLimits(data_bytes=10))
    assert sandboxes(temp_root) == []


def test_timeout_kills_code_and_grandchild(tmp_path, temp_root):
    marker = tmp_path / "pids"
    run = run_python(spawner(marker), limits=FAST)
    pid, grandchild, folder = read_marker(marker)
    assert run.timed_out
    assert gone(pid) and gone(grandchild)
    assert not os.path.exists(folder) and sandboxes(temp_root) == []


def test_finished_code_does_not_wait_for_a_grandchild_holding_the_pipes(tmp_path):
    marker = tmp_path / "pids"
    run = run_python(spawner(marker, then="print('done')"), limits=SandboxLimits(wall_seconds=10))
    assert run.exit_code == 0 and not run.timed_out and run.duration < 5
    assert gone(read_marker(marker)[1])


def test_token_cancellation_raises_quickly_and_cleans_up(tmp_path, temp_root):
    marker = tmp_path / "pids"
    token = CancellationToken(None, marker.exists)
    started = time.monotonic()
    with pytest.raises(OperationCancelled):
        run_python(spawner(marker), cancellation=token)
    assert time.monotonic() - started < 5
    pid, grandchild, folder = read_marker(marker)
    assert gone(pid) and gone(grandchild)
    assert not os.path.exists(folder) and sandboxes(temp_root) == []


def test_token_deadline_raises_timeout_and_cleans_up(temp_root):
    with pytest.raises(OperationTimedOut):
        run_python("import time\ntime.sleep(100)", cancellation=CancellationToken(time.monotonic() + .5))
    assert sandboxes(temp_root) == []


def test_sigterm_handler_is_restored_after_a_run():
    before = signal.getsignal(signal.SIGTERM)
    run_python("pass")
    assert signal.getsignal(signal.SIGTERM) is before


def test_tool_worker_kill_cleans_up_code_and_folder(tmp_path, temp_root):
    marker = tmp_path / "pids"
    registry = ToolRegistry()
    registry.register(RUN_PYTHON, partial(python_tool, data_dir=None))
    with pytest.raises(OperationCancelled):
        registry.execute(ToolCall("run_python", {"code": spawner(marker)}),
                         CancellationToken(None, marker.exists))
    pid, grandchild, folder = read_marker(marker)
    assert gone(pid) and gone(grandchild)
    assert not os.path.exists(folder) and sandboxes(temp_root) == []


def test_tool_through_registry_returns_formatted_result():
    registry = ToolRegistry()
    registry.register(RUN_PYTHON, partial(python_tool, data_dir=None))
    result = registry.execute(ToolCall("run_python", {"code": "print('ok')"}))
    assert result.error is None and result.output.endswith(f"stdout:\nok\n{sandbox.FIX_IT}")


def run_host(tmp_path, body):
    """Run run_python in a separate interpreter acting as Sensai's main thread."""
    script = tmp_path / "host.py"
    script.write_text(textwrap.dedent(body))
    env = {**os.environ, "PYTHONPATH": SRC}
    return subprocess.Popen([sys.executable, str(script)], env=env)


def wait_for(path, timeout=10):
    end = time.monotonic() + timeout
    while not path.exists():
        assert time.monotonic() < end, f"{path} never appeared"
        time.sleep(.02)


def test_sigterm_in_main_thread_cleans_up_then_terminates(tmp_path, temp_root):
    marker = tmp_path / "pids"
    host = run_host(tmp_path, f"""
        from sensai.sandbox import run_python
        run_python({spawner(marker)!r})
        """)
    wait_for(marker)
    host.send_signal(signal.SIGTERM)
    assert host.wait(10) == -signal.SIGTERM
    pid, grandchild, folder = read_marker(marker)
    assert gone(pid) and gone(grandchild)
    assert not os.path.exists(folder) and sandboxes(temp_root) == []


def test_sigterm_with_python_handler_cleans_up_and_cancels(tmp_path, temp_root):
    marker = tmp_path / "pids"
    result = tmp_path / "result"
    host = run_host(tmp_path, f"""
        import signal
        from sensai.core.cancellation import OperationCancelled
        from sensai.sandbox import run_python
        seen = []
        signal.signal(signal.SIGTERM, lambda *args: seen.append("term"))
        try:
            run_python({spawner(marker)!r})
        except OperationCancelled:
            open({str(result)!r}, "w").write(",".join(seen) + " cancelled")
        """)
    wait_for(marker)
    host.send_signal(signal.SIGTERM)
    assert host.wait(10) == 0
    assert result.read_text() == "term cancelled"
    assert sandboxes(temp_root) == []


@pytest.mark.skipif(not LINUX, reason="PR_SET_PDEATHSIG is Linux-only")
def test_parent_death_kills_code_and_next_run_sweeps_its_folder(tmp_path, temp_root):
    marker = tmp_path / "pids"
    host = run_host(tmp_path, f"""
        from sensai.sandbox import run_python
        run_python({spawner(marker)!r})
        """)
    wait_for(marker)
    host.kill()
    host.wait(10)
    pid, grandchild, folder = read_marker(marker)
    assert gone(pid)
    os.kill(grandchild, signal.SIGKILL)  # Out of reach without the SIGTERM clean-up.
    assert os.path.exists(folder)
    run_python("pass")
    assert not os.path.exists(folder)


def test_stale_sweep_removes_dead_owner_folders_only(tmp_path, temp_root):
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    stale = temp_root / f"{PREFIX}{dead.pid}-old_1234"
    live = temp_root / f"{PREFIX}{os.getpid()}-busy1234"
    other = temp_root / f"{PREFIX}notapid-x"
    target = tmp_path / "keep"
    for folder in (stale, live, other, target):
        folder.mkdir()
        (folder / "file").write_text("x")
    link = temp_root / f"{PREFIX}{dead.pid}-link1234"
    link.symlink_to(target)
    run_python("pass")
    assert not stale.exists()
    assert live.exists() and other.exists() and link.is_symlink() and (target / "file").exists()


def test_tool_definition_and_pickleable_handler():
    assert RUN_PYTHON.name == "run_python"
    assert RUN_PYTHON.parameters == {"type": "object", "properties": {"code": {"type": "string"}},
                                     "required": ["code"], "additionalProperties": False}
    assert "standard library" in RUN_PYTHON.description and "no pandas" in RUN_PYTHON.description
    handler = pickle.loads(pickle.dumps(partial(python_tool, data_dir="data")))
    assert handler.keywords == {"data_dir": "data"}
    handler = pickle.loads(pickle.dumps(partial(python_tool, data_dir=None, limits=FAST)))
    assert handler.keywords == {"data_dir": None, "limits": FAST}


def test_python_tool_runs_and_reports_with_the_given_limits():
    result = python_tool({"code": "import time\ntime.sleep(100)"}, limits=SandboxLimits(wall_seconds=.5))
    assert "Time limit reached (0.5 s)" in result.output and result.error == result.output


@pytest.mark.parametrize("run, expected", [
    (SandboxRun("", "", -signal.SIGXCPU, 10.04, False, False),
     "Exit code -24 · 10.0 s\nCPU time limit reached"),
    (SandboxRun("", "", -signal.SIGXFSZ, .2, False, False),
     "Exit code -25 · 0.2 s\nFile size limit reached (10 MB)"),
    (SandboxRun("", "OSError: [Errno 27] File too large\n", 1, .2, False, False),
     "Exit code 1 · 0.2 s\nFile size limit reached (10 MB)\nstderr:\nOSError: [Errno 27] File too large"),
    (SandboxRun("", "", -signal.SIGKILL, .2, False, False), "Exit code -9 · 0.2 s\nKilled by signal SIGKILL"),
    (SandboxRun("a\n", "b", -9, 15.0, True, True),
     "Exit code -9 · 15.0 s\nTime limit reached (15 s)\n(output truncated)\nstdout:\na\nstderr:\nb"),
    (SandboxRun("", "", 0, .25, False, False), "Exit code 0 · 0.2 s"),
])
def test_format_run(run, expected):
    assert format_run(run) == expected
