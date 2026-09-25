import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("copilot_merge_summary", SCRIPTS / "copilot_merge_summary.py")
summary = importlib.util.module_from_spec(spec)
spec.loader.exec_module(summary)

PR = f"https://github.com/{summary.REPOSITORY}/pull/42"
SHA = "a" * 40


class FakeHTTP:
    def __init__(self, **override):
        self.pr = {
            "number": 42, "html_url": PR, "merged_at": "2026-09-25T08:00:00Z",
            "base": {"ref": "main"}, "merge_commit_sha": SHA,
            **override,
        }
        self.calls = []

    def request(self, method, url, token, payload=None, headers=None):
        self.calls.append((method, url, token))
        return self.pr


def valid_output(**override):
    return json.dumps({
        "pr_url": PR, "merge_sha": SHA,
        "evidence_level": "code_landed_not_verified",
        "summary": "Added a small parser and its unit tests.",
        **override,
    })


def test_required_copilot_invoked_read_only_with_bounded_evidence():
    api = FakeHTTP()
    calls = []

    def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout=valid_output(), stderr="")

    with patch.object(summary, "merge_diff", return_value=("diff --git a/parser b/parser\n+x", False)):
        result = summary.summarize(api, "repo-read-token", "copilot-token", 42, runner)
    assert result == "Added a small parser and its unit tests."
    assert api.calls == [("GET", f"{summary.GITHUB_API}/42", "repo-read-token")]
    argv, kwargs = calls[0]
    assert argv[0] == "copilot" and "-p" in argv and "-s" in argv
    assert "--no-ask-user" in argv and "--available-tools=read" in argv
    assert "--no-custom-instructions" in argv and "--no-auto-update" in argv
    assert "diff --git" in argv[argv.index("-p") + 1]
    assert kwargs["env"]["COPILOT_GITHUB_TOKEN"] == "copilot-token"
    assert kwargs["timeout"] == 180


@pytest.mark.parametrize("bad", [
    "not json",
    valid_output(evidence_level="verified"),
    valid_output(pr_url="https://github.com/another/pull/42"),
    valid_output(merge_sha="b" * 40),
    valid_output(summary="Feature complete and approved, all tests passed."),
    valid_output(summary="Added https://example.com and a parser."),
    valid_output(summary="Short"),
    valid_output(summary="Test code\nDangerous next line"),
    json.dumps({"summary": "text"}),
])
def test_machine_validation_rejects_unsupported_claims_or_shape(bad):
    with pytest.raises(summary.SyncError):
        summary.validate_summary(bad, PR, SHA)


def test_fail_closed_before_copilot_for_non_main_or_unmerged_pr():
    for fields in ({"merged_at": None}, {"base": {"ref": "develop"}}, {"merge_commit_sha": None}):
        api = FakeHTTP(**fields)
        with pytest.raises(summary.SyncError):
            summary.summarize(api, "repo-read-token", "copilot-token", 42,
                              runner=lambda *a, **k: pytest.fail("must not call CLI"))


def test_copilot_failure_does_not_print_raw_stderr():
    api = FakeHTTP()
    with patch.object(summary, "merge_diff", return_value=("+code", False)):
        with pytest.raises(summary.SyncError, match="Copilot CLI failed") as exc:
            summary.summarize(
                api, "repo-read-token", "copilot-token", 42,
                runner=lambda *a, **k: SimpleNamespace(
                    returncode=1, stdout="", stderr="PRIVATE-TOKEN",
                ),
            )
    assert "PRIVATE-TOKEN" not in str(exc.value)


def test_git_diff_is_first_parent_and_no_shell():
    calls = []

    def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(stdout="diff --git a/x b/x\n+line", stderr="", returncode=0)

    with patch.object(summary.subprocess, "run", side_effect=runner):
        diff, truncated = summary.merge_diff(SHA)
    assert not truncated and "diff --git" in diff
    argv, kwargs = calls[0]
    assert argv[:2] == ["git", "diff"]
    assert argv[-2:] == [f"{SHA}^1", SHA]
    assert "shell" not in kwargs


def test_missing_copilot_auth_fails_explicitly(capsys):
    with patch.dict(summary.os.environ, {"GITHUB_TOKEN": "read", "COPILOT_GITHUB_TOKEN": ""}):
        with patch.object(summary.sys, "argv", ["copilot_merge_summary.py", "--pr", "42"]):
            assert summary.main() == 1
    assert "must both be configured" in capsys.readouterr().err


def test_workflow_gates_sync_on_tests_and_copilot_without_exposing_tracker_credentials():
    workflow = (SCRIPTS.parent / ".github/workflows/sync-merge-evidence.yml").read_text()
    before, after = workflow.split("\n  sync:\n", 1)
    assert "types: [closed]" in before
    assert "  inactive:\n" in before
    assert "No tracker writes were attempted." in before
    assert "  unit-tests:\n" in before
    assert "ref: main" in before
    assert "python -m pytest -q tests/unit" in before
    assert "  copilot-summary:\n" in before
    assert "scripts/copilot_merge_summary.py" in before
    assert "copilot-requests: write" in before
    assert "GH_PROJECT_TOKEN" not in before and "NOTION_TOKEN" not in before
    active = "github.repository == 'OmarCodes022/Sensai' && (github.event_name == 'workflow_dispatch' || github.event.pull_request.merged == true) && vars.SENSAI_EVIDENCE_SYNC_ENABLED == 'true'"
    assert before.count(active) == 2
    assert active in after
    assert "needs: [unit-tests, copilot-summary]" in after
    assert "scripts/sync_merge_evidence.py" in after
    assert "GH_PROJECT_TOKEN: ${{ secrets.GH_PROJECT_TOKEN }}" in after
    assert "NOTION_TOKEN: ${{ secrets.NOTION_TOKEN }}" in after
