import importlib.util
import subprocess
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "aws_mirror", Path(__file__).resolve().parents[2] / "infra/aws-mirror/mirror.py"
)
mirror = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mirror)

KEY = "-----BEGIN OPENSSH PRIVATE KEY-----\nlocal test only\n"


def git(*args, cwd=None):
    return subprocess.check_output(
        ["git", *map(str, args)], cwd=cwd, text=True, stderr=subprocess.PIPE
    ).strip()


@pytest.fixture
def repositories(tmp_path, monkeypatch):
    source = tmp_path / "source.git"
    target = tmp_path / "target.git"
    work = tmp_path / "work"
    git("init", "--bare", source)
    git("init", "--bare", target)
    git("init", "-b", "main", work)
    git("config", "user.name", "Mirror test", cwd=work)
    git("config", "user.email", "test@example.invalid", cwd=work)
    (work / "file.txt").write_text("first", encoding="utf-8")
    git("add", "file.txt", cwd=work)
    git("commit", "-m", "first", cwd=work)
    first = git("rev-parse", "HEAD", cwd=work)
    git("push", source, "HEAD:main", cwd=work)
    git("push", target, "HEAD:main", cwd=work)
    (work / "file.txt").write_text("second", encoding="utf-8")
    git("commit", "-am", "second", cwd=work)
    second = git("rev-parse", "HEAD", cwd=work)
    git("push", source, "HEAD:main", cwd=work)
    monkeypatch.setattr(mirror, "SOURCE", str(source))
    monkeypatch.setattr(mirror, "DESTINATION", str(target))
    return source, target, work, first, second


def test_only_exact_tested_tip_fast_forwards(repositories):
    _, target, _, first, second = repositories
    assert mirror.mirror(first, KEY) == {"status": "waiting_for_ci", "source": second}
    assert git(f"--git-dir={target}", "rev-parse", "refs/heads/main") == first
    assert mirror.mirror(second, KEY) == {
        "status": "mirrored", "source": second, "previous": first
    }
    assert git(f"--git-dir={target}", "rev-parse", "refs/heads/main") == second
    assert mirror.mirror(second, KEY) == {"status": "up_to_date", "source": second}


def test_rejects_divergent_destination(repositories):
    _, target, work, _, second = repositories
    git("remote", "add", "target", target, cwd=work)
    git("fetch", "target", "main", cwd=work)
    git("switch", "-c", "different", "FETCH_HEAD", cwd=work)
    (work / "file.txt").write_text("different", encoding="utf-8")
    git("commit", "-am", "different", cwd=work)
    different = git("rev-parse", "HEAD", cwd=work)
    git("push", target, "HEAD:main", cwd=work)
    with pytest.raises(RuntimeError, match="merge-base failed"):
        mirror.mirror(second, KEY)
    assert git(f"--git-dir={target}", "rev-parse", "refs/heads/main") == different


@pytest.mark.parametrize("sha", ["", "a" * 39, "z" * 40])
def test_rejects_bad_marker(sha):
    with pytest.raises(ValueError, match="commit SHA"):
        mirror.mirror(sha, KEY)


def test_rejects_bad_key():
    with pytest.raises(ValueError, match="OpenSSH private key"):
        mirror.mirror("a" * 40, "not a key")
