"""T19 review fixes (PR #96): exit check, sweep shape, bounded drain, stderr cut."""

import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

import pytest

from sensai import sandbox
from sensai.sandbox import PREFIX, SandboxLimits, run_python


@pytest.fixture(autouse=True)
def temp_root(tmp_path, monkeypatch):
    root = tmp_path / "temp-root"
    root.mkdir()
    monkeypatch.setenv("TMPDIR", str(root))
    monkeypatch.setattr(tempfile, "tempdir", str(root))
    return root


# --- regression tests from the review, verbatim -------------------------------------

def test_a_stopped_child_is_not_reported_as_exited():
    child = subprocess.Popen(["sleep", "30"])
    try:
        os.kill(child.pid, signal.SIGSTOP)
        time.sleep(.2)
        assert not sandbox._exited(child)
    finally:
        child.kill()
        child.wait()


def test_stale_sweep_keeps_folders_that_mkdtemp_could_not_have_made(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    gone = subprocess.Popen(["true"]); gone.wait()
    ours = tmp_path / f"{sandbox.PREFIX}{gone.pid}-abcd1234"
    decoys = [tmp_path / f"{sandbox.PREFIX}{gone.pid}",
              tmp_path / f"{sandbox.PREFIX}{gone.pid}-my-project"]
    for folder in [ours, *decoys]:
        folder.mkdir(); (folder / "keep").write_text("x")
    sandbox.remove_stale_folders()
    assert not ours.exists()
    assert all((folder / "keep").exists() for folder in decoys)


# --- exit check ---------------------------------------------------------------------

@pytest.mark.parametrize("how, code", [
    ("exit", "raise SystemExit(3)"),
    ("killed", "import os, signal\nos.kill(os.getpid(), signal.SIGKILL)"),
])
def test_exited_and_killed_children_count_as_exited(how, code):
    child = subprocess.Popen([sys.executable, "-c", code])
    end = time.monotonic() + 5
    while not sandbox._exited(child):
        assert time.monotonic() < end, how
        time.sleep(.02)
    child.wait()


# --- sweep shape --------------------------------------------------------------------

@pytest.mark.parametrize("suffix", ["abcd123", "abcd12345", "ABCD1234", "abcd-123", "abcd.123",
                                    "abcd123é", "abcd123\n"])
def test_stale_sweep_keeps_names_outside_the_mkdtemp_alphabet(temp_root, suffix):
    gone = subprocess.Popen(["true"])
    gone.wait()
    folder = temp_root / f"{PREFIX}{gone.pid}-{suffix}"
    folder.mkdir()
    sandbox.remove_stale_folders()
    assert folder.exists()


def test_stale_sweep_removes_a_real_mkdtemp_folder_of_a_dead_owner(temp_root):
    gone = subprocess.Popen(["true"])
    gone.wait()
    folder = Path(tempfile.mkdtemp(prefix=f"{PREFIX}{gone.pid}-"))
    (folder / "data.csv").write_text("x")
    sandbox.remove_stale_folders()
    assert not folder.exists()


# --- grandchild keeping the pipes busy after the code exits -------------------------

FLOOD = r'''
import fcntl, os, threading
for fd in (1, 2):
    if hasattr(fcntl, "F_SETPIPE_SZ"):
        try:
            fcntl.fcntl(fd, fcntl.F_SETPIPE_SZ, 1 << 20)
        except OSError:
            pass
def flood(fd):
    while True:
        os.write(fd, b"g" * 65536)
threading.Thread(target=flood, args=(2,), daemon=True).start()
flood(1)
'''


def test_busy_pipes_after_exit_are_drained_briefly_not_until_the_wall_limit():
    code = (f"import subprocess, sys, time\nsubprocess.Popen([sys.executable, '-c', {FLOOD!r}])\n"
            "time.sleep(.5)\nprint('done', flush=True)\n")
    for _ in range(3):  # The pipes are not always busy at the exact exit moment.
        started = time.monotonic()
        run = run_python(code, limits=SandboxLimits(wall_seconds=10, output_chars=100))
        assert time.monotonic() - started < 3
        assert run.exit_code == 0 and not run.timed_out and run.duration < 3
        assert run.truncated


# --- stderr tail cut ----------------------------------------------------------------

def test_stderr_tail_cut_starts_on_a_whole_character():
    output = sandbox._Output(8)
    output.add("err", "\U0001F600\U0001F600\U0001F600x".encode())
    assert bytes(output.err).decode("utf-8") == "\U0001F600x" and output.cut


def test_stderr_tail_cut_skips_at_most_three_continuation_bytes():
    output = sandbox._Output(6)
    output.add("err", b"x" + b"\x80" * 10)
    assert bytes(output.err) == b"\x80" * 3


def test_run_stderr_has_no_leading_replacement_character(temp_root):
    # The folder path in stderr shrinks to ".", so the byte tail fits the character limit.
    folder = len(f"{os.path.realpath(temp_root)}{os.sep}{PREFIX}{os.getpid()}-") + 8
    chars = folder // 3
    pad = "" if (4 * chars - folder) % 2 else "x"  # An odd number of é bytes cuts one in half.
    code = f"import os, sys\nsys.stderr.write('é' * 400 + {pad!r} + os.getcwd())"
    run = run_python(code, limits=SandboxLimits(output_chars=chars))
    assert run.truncated and run.stderr.endswith(pad + ".")
    assert "�" not in run.stderr and set(run.stderr[:-1 - len(pad)]) == {"é"}
