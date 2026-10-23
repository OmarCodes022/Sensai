"""T19 sandbox, adversarial: leftovers, odd output, isolation and limits (real children)."""

from functools import partial
import json
import os
from pathlib import Path
import signal
import stat
import sys
import tempfile
import textwrap
import time

import pytest

from sensai import sandbox
from sensai.core.cancellation import CancellationToken, OperationCancelled
from sensai.core.ports import ToolCall
from sensai.sandbox import PREFIX, RUN_PYTHON, SandboxLimits, format_run, python_tool, run_python
from sensai.tools import ToolRegistry

FAST = SandboxLimits(wall_seconds=1.5)
LINUX = sys.platform.startswith("linux")


@pytest.fixture(autouse=True)
def temp_root(tmp_path, monkeypatch):
    """Private temp root (also for spawned workers); no sandbox folder may survive a test."""
    root = tmp_path / "temp-root"
    root.mkdir()
    monkeypatch.setenv("TMPDIR", str(root))
    monkeypatch.setattr(tempfile, "tempdir", str(root))
    yield root
    assert sandboxes(root) == []


@pytest.fixture
def pids():
    """Pids a test spawned indirectly; any survivor is killed, then the test fails."""
    seen = []
    yield seen
    alive = [pid for pid in seen if not gone(pid, wait=2)]
    for pid in alive:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    assert not alive, f"processes left behind: {alive}"


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


def sandboxes(root):
    return sorted(p.name for p in root.iterdir() if p.name.startswith(PREFIX))


def grandchild_code(marker, child="import time; time.sleep(100)", popen="", then="time.sleep(100)"):
    """Code that starts one grandchild, then atomically writes 'pid grandchild cwd' to marker."""
    return "\n".join([
        "import os, subprocess, sys, time",
        f"child = subprocess.Popen([sys.executable, '-c', {child!r}]{popen})",
        f"with open({str(marker)!r} + '.tmp', 'w') as f:",
        "    f.write(f'{os.getpid()} {child.pid} {os.getcwd()}')",
        f"os.rename({str(marker)!r} + '.tmp', {str(marker)!r})",
        then, ""])


def read_marker(marker, pids):
    pid, grandchild, folder = marker.read_text().split(" ", 2)
    pids += [int(pid), int(grandchild)]
    return int(pid), int(grandchild), folder


# --- stale-folder sweep ------------------------------------------------------------

@pytest.mark.parametrize("owner", [str(10 ** 30), "\u00b2"])
def test_sweep_ignores_folders_with_unusable_owner_pid(temp_root, owner):
    # Any code run in the sandbox can create this folder in the shared temp dir by absolute path.
    odd = temp_root / f"{PREFIX}{owner}-x"
    odd.mkdir()
    try:
        run = run_python("print('still works')", limits=FAST)
    finally:
        odd.rmdir()
    assert run.stdout == "still works\n"


def test_sweep_leaves_files_and_other_users_names_alone(temp_root):
    (temp_root / f"{PREFIX}1-file").write_text("not a folder")
    (temp_root / "sensai-sandboxx-1-x").mkdir()
    run_python("pass", limits=FAST)
    assert (temp_root / f"{PREFIX}1-file").exists() and (temp_root / "sensai-sandboxx-1-x").exists()
    (temp_root / f"{PREFIX}1-file").unlink()


# --- process leftovers -------------------------------------------------------------

def test_grandchild_flooding_the_pipes_after_main_exits_does_not_hang(tmp_path, pids):
    marker = tmp_path / "pids"
    flood = "import sys\nwhile True: sys.stdout.write('g' * 65536); sys.stderr.write('e' * 999)"
    started = time.monotonic()
    run = run_python(grandchild_code(marker, flood, then="time.sleep(.3)"),
                     limits=SandboxLimits(wall_seconds=8, output_chars=100))
    _, grandchild, _ = read_marker(marker, pids)
    assert time.monotonic() - started < 6
    assert run.exit_code == 0 and run.truncated and gone(grandchild)


def test_grandchild_with_closed_stdio_is_killed_after_success(tmp_path, pids):
    marker = tmp_path / "pids"
    popen = ", stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL"
    run = run_python(grandchild_code(marker, popen=popen, then="print('done')"), limits=FAST)
    _, grandchild, folder = read_marker(marker, pids)
    assert run.exit_code == 0 and run.stdout == "done\n" and not run.timed_out
    assert gone(grandchild) and not os.path.exists(folder)


def test_grandchild_ignoring_sigterm_is_killed_on_timeout(tmp_path, pids):
    marker = tmp_path / "pids"
    stubborn = "import signal, time\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\ntime.sleep(100)"
    run = run_python(grandchild_code(marker, stubborn), limits=FAST)
    pid, grandchild, folder = read_marker(marker, pids)
    assert run.timed_out and gone(pid) and gone(grandchild) and not os.path.exists(folder)


def test_grandchild_is_killed_after_an_exception(tmp_path, pids):
    marker = tmp_path / "pids"
    run = run_python(grandchild_code(marker, then="raise RuntimeError('boom')"), limits=FAST)
    _, grandchild, folder = read_marker(marker, pids)
    assert run.exit_code == 1 and "RuntimeError: boom" in run.stderr
    assert gone(grandchild) and not os.path.exists(folder)


def test_grandchild_is_killed_at_the_cpu_limit(tmp_path, pids):
    marker = tmp_path / "pids"
    limits = SandboxLimits(wall_seconds=10, cpu_seconds=1)
    run = run_python(grandchild_code(marker, then="while True: pass"), limits=limits)
    pid, grandchild, folder = read_marker(marker, pids)
    assert run.exit_code == -signal.SIGXCPU and "CPU time limit reached" in format_run(run, limits)
    assert gone(pid) and gone(grandchild) and not os.path.exists(folder)


@pytest.mark.parametrize("escape", ["os.setsid()", "os.setpgid(0, 0)"])
def test_documented_gap_grandchild_leaving_the_group_survives(tmp_path, escape):
    """Document-only (README): a descendant that leaves the process group is out of reach.

    The run itself still returns quickly and its folder is removed.
    """
    marker = tmp_path / "pids"
    child = f"import os, time\n{escape}\ntime.sleep(100)"
    run = run_python(grandchild_code(marker, child, then="time.sleep(.3)"), limits=FAST)
    pid, grandchild, folder = read_marker(marker, [])
    try:
        assert run.exit_code == 0 and run.duration < 1.4 and not os.path.exists(folder)
        assert gone(pid) and not gone(grandchild, wait=.3)
    finally:
        os.kill(grandchild, signal.SIGKILL)


def test_cpu_limit_with_sigxcpu_ignored_hits_the_hard_limit():
    limits = SandboxLimits(wall_seconds=10, cpu_seconds=1)
    run = run_python("import signal\nsignal.signal(signal.SIGXCPU, signal.SIG_IGN)\nwhile True: pass",
                     limits=limits)
    assert run.exit_code == -signal.SIGKILL and not run.timed_out and run.duration < 4
    assert "Killed by signal SIGKILL" in format_run(run, limits)


def kill_worker_after_files(tmp_path, temp_root, pids, count):
    """Real ControlledTool path: Ctrl+C once the code made `count` folders, then check leftovers."""
    marker = tmp_path / "pids"
    many = (f"for i in range({count}):\n"
            "    os.mkdir(f'd{i}'); open(f'd{i}/f', 'w').close()\n"
            "time.sleep(100)")
    registry = ToolRegistry()
    registry.register(RUN_PYTHON, partial(python_tool, data_dir=None))

    def made_them():
        if not marker.exists():
            return False
        try:
            return sum(1 for _ in os.scandir(marker.read_text().split(" ", 2)[2])) > count
        except OSError:
            return False

    with pytest.raises(OperationCancelled):
        registry.execute(ToolCall("run_python", {"code": grandchild_code(marker, then=many)}),
                         CancellationToken(None, made_them))
    pid, grandchild, folder = read_marker(marker, pids)
    left = os.path.exists(folder)
    __import__("shutil").rmtree(folder, ignore_errors=True)
    assert gone(pid) and gone(grandchild)
    assert not left


def test_worker_kill_after_a_few_thousand_files_removes_the_folder(tmp_path, temp_root, pids):
    kill_worker_after_files(tmp_path, temp_root, pids, 2000)


def test_worker_kill_after_many_files_removes_the_folder(tmp_path, temp_root, pids):
    """Ctrl+C on /run: what the killed worker could not delete, the CLI sweeps before the prompt."""
    from fakes import FakeClient
    from sensai.chat.session import ChatSession
    from sensai.cli import main as cli

    marker = tmp_path / "pid"
    script = tmp_path / "many.py"
    script.write_text(
        "import os, time\n"
        "for i in range(40000):\n"
        "    os.mkdir(f'd{i}'); open(f'd{i}/f', 'w').close()\n"
        f"open({str(marker)!r} + '.tmp', 'w').write(f'{{os.getpid()}} {{os.getcwd()}}')\n"
        f"os.rename({str(marker)!r} + '.tmp', {str(marker)!r})\n"
        "time.sleep(100)\n", encoding="utf-8")
    inputs = iter([f"/run {script}", "exit"])
    folder_at_prompt = []

    def read(prompt):
        if marker.exists():
            folder_at_prompt.append(os.path.exists(marker.read_text().split(" ", 1)[1]))
        return next(inputs)

    lines = []
    cli.repl(ChatSession(FakeClient(), "model", "sys"), read=read,
             write=lambda *args, **kwargs: lines.append(" ".join(map(str, args))),
             cancel_requested=marker.exists)
    pids.append(int(marker.read_text().split(" ", 1)[0]))
    assert "Exécution interrompue" in "\n".join(lines)
    assert folder_at_prompt == [False]


def test_worker_deadline_kills_code_and_removes_folder(tmp_path, temp_root, pids):
    marker = tmp_path / "pids"
    registry = ToolRegistry()
    registry.register(RUN_PYTHON, partial(python_tool, data_dir=None), timeout=1.5)
    result = registry.execute(ToolCall("run_python", {"code": grandchild_code(marker)}))
    assert result.error == "tool timed out"
    pid, grandchild, folder = read_marker(marker, pids)
    assert gone(pid) and gone(grandchild) and not os.path.exists(folder)


# --- output ------------------------------------------------------------------------

def test_invalid_utf8_and_nul_bytes_are_replaced_not_fatal():
    run = run_python("import sys\nsys.stdout.buffer.write(b'\\xff\\xfeok\\x00\\n')\n"
                     "sys.stderr.buffer.write(b'\\xc3(')", limits=FAST)
    assert run.exit_code == 0
    assert run.stdout == "\ufffd\ufffdok\x00\n" and run.stderr == "\ufffd("


def test_ten_million_chars_on_stderr_keep_the_traceback_tail(monkeypatch):
    sizes = []

    class Recording(sandbox._Output):
        def add(self, name, data):
            super().add(name, data)
            sizes.append(len(self.out) + len(self.err))

    monkeypatch.setattr(sandbox, "_Output", Recording)
    limits = SandboxLimits(wall_seconds=10, output_chars=1000)
    code = ("import sys\nprint('HEAD' + 'o' * 10_000_000)\nsys.stderr.write('e' * 10_000_000 + '\\n')\n"
            "def fail():\n    raise LookupError('the end')\nfail()\n")
    started = time.monotonic()
    run = run_python(code, limits=limits)
    assert time.monotonic() - started < 6
    assert run.exit_code == 1 and run.truncated
    assert run.stdout.startswith("HEAD") and len(run.stdout) == 1000
    assert len(run.stderr) == 1000 and run.stderr.rstrip().endswith("LookupError: the end")
    assert 'File "main.py", line 5, in fail' in run.stderr
    assert max(sizes) <= 2 * 4 * 1000 + 65536
    text = format_run(run, limits)
    assert "(output truncated)" in text and len(text) < 2200


def test_output_after_the_code_closes_its_stdout():
    code = ("import os, sys, time\nprint('before', flush=True)\nos.close(1)\ntime.sleep(.3)\n"
            "print('after', file=sys.stderr)\n")
    run = run_python(code, limits=FAST)
    assert run.stdout == "before\n" and "after" in run.stderr and not run.timed_out


def test_code_closing_both_pipes_is_still_stopped_by_the_wall_limit():
    started = time.monotonic()
    run = run_python("import os\nos.close(1)\nos.close(2)\nwhile True: pass",
                     limits=SandboxLimits(wall_seconds=1))
    assert run.timed_out and time.monotonic() - started < 3


def test_stdout_cut_counts_characters_for_four_byte_text():
    run = run_python("print('\U0001F600' * 50)", limits=SandboxLimits(output_chars=10))
    assert run.stdout == "\U0001F600" * 10 and run.truncated


# --- isolation of the child --------------------------------------------------------

def test_stdin_is_empty_and_input_gets_eof():
    run = run_python("import sys\nprint(repr(sys.stdin.read()))\ntry:\n    input()\n"
                     "except EOFError:\n    print('eof')", limits=FAST)
    assert run.stdout == "''\neof\n"


def test_child_inherits_no_extra_file_descriptors_even_in_the_worker():
    code = "import os\nprint(sorted(int(fd) for fd in os.listdir('/proc/self/fd')))"
    if not os.path.isdir("/proc/self/fd"):
        pytest.skip("needs /proc")
    direct = run_python(code, limits=FAST)
    registry = ToolRegistry()
    registry.register(RUN_PYTHON, partial(python_tool, data_dir=None))
    worker = registry.execute(ToolCall("run_python", {"code": code}))
    # 0-2 plus the descriptor listdir itself opened.
    assert json.loads(direct.stdout)[:3] == [0, 1, 2] and len(json.loads(direct.stdout)) == 4
    assert worker.output.endswith("stdout:\n[0, 1, 2, 3]")


def test_cwd_home_and_tempfile_are_the_throwaway_folder():
    code = ("import os, tempfile\ncwd = os.getcwd()\n"
            "print(os.path.expanduser('~') == cwd, tempfile.gettempdir() == cwd)")
    assert run_python(code, limits=FAST).stdout == "True True\n"


def test_environment_has_no_parent_secrets_inside_the_worker(monkeypatch):
    for name in ("SENSAI_TOKEN", "OLLAMA_HOST", "OPENAI_API_KEY", "AWS_SECRET_ACCESS_KEY"):
        monkeypatch.setenv(name, "leak-me")
    registry = ToolRegistry()
    registry.register(RUN_PYTHON, partial(python_tool, data_dir=None))
    result = registry.execute(ToolCall("run_python", {
        "code": "import os\nprint(sorted(os.environ))\nprint(open('/proc/self/environ','rb').read())"}))
    assert "leak-me" not in result.output and result.error is None
    assert "['HOME', 'LANG', 'PATH', 'PYTHONDONTWRITEBYTECODE', 'PYTHONIOENCODING', 'TMPDIR']" in result.output


@pytest.mark.skipif(not LINUX, reason="Linux limits and prctl")
def test_limits_are_set_and_cannot_be_raised_by_the_code():
    limits = SandboxLimits(cpu_seconds=3, memory_bytes=300 * 1024 * 1024, file_bytes=2 * 1024 * 1024)
    code = textwrap.dedent("""\
        import ctypes, os, resource
        r = {n: resource.getrlimit(getattr(resource, n)) for n in
             ("RLIMIT_CPU", "RLIMIT_AS", "RLIMIT_FSIZE", "RLIMIT_CORE")}
        sig = ctypes.c_int()
        ctypes.CDLL(None).prctl(2, ctypes.byref(sig), 0, 0, 0)
        try:
            resource.setrlimit(resource.RLIMIT_AS, (resource.RLIM_INFINITY,) * 2)
            raised = True
        except (ValueError, OSError):
            raised = False
        print(r, sig.value, raised, os.getpgid(0) == os.getpid())
        """)
    run = run_python(code, limits=limits)
    assert run.stdout.strip() == (
        f"{{'RLIMIT_CPU': (3, 4), 'RLIMIT_AS': ({300 * 1024 * 1024}, {300 * 1024 * 1024}), "
        f"'RLIMIT_FSIZE': ({2 * 1024 * 1024}, {2 * 1024 * 1024}), 'RLIMIT_CORE': (0, 0)}} "
        f"{int(signal.SIGKILL)} False True")


def test_file_limit_applies_to_truncate_and_grandchildren():
    limits = SandboxLimits(file_bytes=1024 * 1024)
    code = textwrap.dedent("""\
        import subprocess, sys
        p = subprocess.run([sys.executable, "-c",
                            "open('g.bin', 'wb').write(b'x' * 2 * 1024 * 1024)"])
        print("grandchild", p.returncode != 0)
        import os
        os.truncate("g.bin", 5 * 1024 * 1024)
        """)
    run = run_python(code, limits=limits)
    assert run.stdout == "grandchild True\n" and run.exit_code == 1
    assert "File size limit reached (1 MB)" in format_run(run, limits)


@pytest.mark.skipif(not LINUX, reason="RLIMIT_AS is only enforced on Linux")
def test_memory_limit_applies_to_grandchildren():
    limits = SandboxLimits(memory_bytes=256 * 1024 * 1024)
    code = ("import subprocess, sys\np = subprocess.run([sys.executable, '-c', 'bytearray(1024 ** 3)'],"
            " capture_output=True, text=True)\nprint(p.returncode, 'MemoryError' in p.stderr)")
    assert run_python(code, limits=limits).stdout == "1 True\n"


def test_lone_surrogate_in_code_is_an_error_result_not_a_crash(temp_root):
    registry = ToolRegistry()
    registry.register(RUN_PYTHON, partial(python_tool, data_dir=None))
    result = registry.execute(ToolCall("run_python", {"code": "print('\ud83d')"}))
    assert result.output == "" and "UnicodeEncodeError" in result.error
    assert sandboxes(temp_root) == []


# --- data folder -------------------------------------------------------------------

@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="needs FIFOs")
def test_data_folder_fifo_and_dir_symlink_are_skipped_without_hanging(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    os.mkfifo(data / "pipe.csv")
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / "elsewhere" / "x.txt").write_text("x")
    (data / "dirlink").symlink_to(tmp_path / "elsewhere")
    (data / "ok.csv").write_text("a,b\n")
    run = run_python("import os\nprint(sorted(os.listdir()))", data, limits=FAST)
    assert run.stdout == "['main.py', 'ok.csv']\n"


def test_data_folder_reached_through_a_symlink_and_exact_size_cap(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "a.bin").write_bytes(b"x" * 6)
    (data / "b.bin").write_bytes(b"y" * 4)
    link = tmp_path / "link"
    link.symlink_to(data)
    run = run_python("import os\nprint(sum(os.path.getsize(f) for f in ('a.bin', 'b.bin')))",
                     str(link), limits=SandboxLimits(data_bytes=10))
    assert run.stdout == "10\n"


def test_data_files_are_copies_the_code_cannot_alter(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "engagement.csv").write_text("orig")
    run = run_python("open('engagement.csv', 'w').write('changed')\nimport os\nos.remove('engagement.csv')",
                     data, limits=FAST)
    assert run.exit_code == 0 and (data / "engagement.csv").read_text() == "orig"


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads anything")
def test_unreadable_data_file_is_skipped_silently(tmp_path):
    """Documents current behaviour: no error, the file is just missing in the sandbox."""
    data = tmp_path / "data"
    data.mkdir()
    secret = data / "locked.csv"
    secret.write_text("x")
    secret.chmod(0)
    try:
        run = run_python("import os\nprint(os.listdir())", data, limits=FAST)
    finally:
        secret.chmod(stat.S_IRUSR | stat.S_IWUSR)
    assert run.stdout == "['main.py']\n"


def test_missing_data_folder_message_through_the_worker(tmp_path):
    registry = ToolRegistry()
    registry.register(RUN_PYTHON, partial(python_tool, data_dir=str(tmp_path / "gone")))
    result = registry.execute(ToolCall("run_python", {"code": "print(1)"}))
    assert result.output == "" and result.error.startswith("data folder not found")


def test_code_that_stops_itself_is_killed_at_the_wall_limit():
    started = time.monotonic()
    run = run_python("import os, signal\nos.kill(os.getpid(), signal.SIGSTOP)",
                     limits=SandboxLimits(wall_seconds=1))
    assert run.timed_out and run.exit_code == -signal.SIGKILL and time.monotonic() - started < 3


def test_code_that_leaves_its_group_is_still_stopped_at_the_wall_limit(tmp_path, pids):
    from sandbox_handlers import fast_python_tool

    marker = tmp_path / "pid"
    code = (f"import os, time\nos.setpgid(0, os.getpgid(os.getppid()))\n"
            f"open({str(marker)!r}, 'w').write(str(os.getpid()))\ntime.sleep(100)")
    registry = ToolRegistry()
    registry.register(RUN_PYTHON, partial(fast_python_tool, data_dir=None), timeout=5)
    started = time.monotonic()
    result = registry.execute(ToolCall("run_python", {"code": code}))
    pids.append(int(marker.read_text()))
    assert time.monotonic() - started < 4
    assert "time limit reached" in result.output.lower()
