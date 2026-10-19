"""Exercise signal handling with local Python children; never start SSH or HTTP."""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[3]

# A separate interpreter protects pytest if a regression restores default signal handling.
DRIVER = r'''
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

root, scenario, pid_file = sys.argv[1:]
sys.path.insert(0, str(Path(root) / "src"))
from sensai.cli import remote
real_popen = subprocess.Popen
child = None
original = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGHUP, signal.SIGTERM)}

def forbidden(*args, **kwargs):
    raise AssertionError("No real SSH or HTTP is allowed")

def start_child(*args, **kwargs):
    global child
    resistant = "signal.signal(signal.SIGTERM, signal.SIG_IGN);" if scenario == "resistant" else ""
    child = real_popen([sys.executable, "-c", "import signal,time;" + resistant +
                       "print('ready',flush=True);time.sleep(60)"],
                      stdout=subprocess.PIPE, text=True, start_new_session=True)
    Path(pid_file).write_text(str(child.pid))
    assert child.stdout.readline().strip() == "ready"
    wait = child.wait
    child.wait = lambda timeout=None: wait(timeout=min(timeout, .15) if timeout is not None else None)
    if scenario == "spawn-interrupt":
        os.kill(os.getpid(), signal.SIGTERM)
    return child

def chat(*args):
    if scenario in ("SIGTERM", "SIGHUP"):
        os.kill(os.getpid(), getattr(signal, scenario))
    elif scenario == "chat-interrupt":
        try:
            os.kill(os.getpid(), signal.SIGINT)
        except KeyboardInterrupt:
            pass
        else:
            raise AssertionError("Chat must retain normal Ctrl+C behavior")
        assert child.poll() is None

def interrupt_cleanup(signum, handler):
    result = real_signal(signum, handler)
    if signum == signal.SIGTERM and handler == signal.SIG_IGN:
        os.kill(os.getpid(), signal.SIGINT)
    return result

try:
    remote.HTTPConnection = forbidden
    remote.subprocess.Popen = start_child
    remote.ollama_running = lambda: scenario == "reused"
    remote._wait_for_ollama = lambda process: None
    remote.cli.run_chat = chat
    if scenario == "cleanup-interrupt":
        real_signal = signal.signal
        signal.signal = interrupt_cleanup
    remote.Settings = lambda: remote.cli.Settings(
        _env_file=None, SENSAI_MODEL="model", SENSAI_SSH_HOST="alias",
        OLLAMA_HOST="http://127.0.0.1:11435",
        SENSAI_PROMPT=str(Path(root) / "src/sensai/chat/system_prompt.txt"))
    if scenario == "reused":
        start_child()
        remote.subprocess.Popen = forbidden
    result = remote.main([])
    assert all(signal.getsignal(sig) == handler for sig, handler in original.items())
    if scenario == "reused":
        assert child.poll() is None, "Existing process must be left running"
    else:
        assert child.returncode is not None, "Owned child was not waited for/reaped"
        try:
            os.waitpid(child.pid, os.WNOHANG)
        except ChildProcessError:
            pass
        else:
            raise AssertionError("Owned child was not reaped")
    expected = 128 + getattr(signal, scenario) if scenario in ("SIGTERM", "SIGHUP") else 0
    if scenario == "spawn-interrupt":
        expected = 128 + signal.SIGTERM
    assert result == expected, (result, expected)
    if scenario == "resistant":
        assert child.returncode == -signal.SIGKILL
    print(json.dumps({"status": result, "returncode": child.returncode}))
finally:
    if child is not None:
        if child.poll() is None:
            child.kill()
        child.wait(timeout=3)
        child.stdout.close()
        Path(pid_file).unlink(missing_ok=True)
'''


@pytest.mark.parametrize("scenario", [
    "SIGTERM", "SIGHUP", "spawn-interrupt", "chat-interrupt", "cleanup-interrupt",
    "resistant", "reused",
])
def test_local_child_lifetime_and_signals(tmp_path, scenario):
    pid_file = tmp_path / "child.pid"
    process = subprocess.Popen(
        [sys.executable, "-c", DRIVER, str(ROOT), scenario, str(pid_file)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 0, (stdout, stderr)
        result = json.loads(stdout)
        assert result["status"] in (0, 128 + signal.SIGTERM, 128 + signal.SIGHUP)
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=3)
        # If broken signal handling killed the driver, reclaim its known test child.
        if pid_file.exists():
            try:
                os.kill(int(pid_file.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass
