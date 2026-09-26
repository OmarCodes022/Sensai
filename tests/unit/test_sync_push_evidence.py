import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("sync_push_evidence", SCRIPTS / "sync_push_evidence.py")
push = importlib.util.module_from_spec(spec)
spec.loader.exec_module(push)

BEFORE = "a" * 40
AFTER = "b" * 40
TASK = "task-1"
FEATURE = "feature-1"
ISSUE = f"https://github.com/{push.ORG_REPOSITORY}/issues/18"


def row(source, kind, page_id, issue=None):
    task = kind == "tasks"
    title = "T07 Set up creator brand facts" if task else "M3 Brand memory"
    properties = {
        "Task" if task else "Feature": {
            "type": "title", "title": [{"plain_text": title}],
        },
        "Feature IDs" if task else "ID": {
            "type": "rich_text", "rich_text": [{"plain_text": "M3"}],
        },
        "GitHub issue" if task else "Issue URL": {"type": "url", "url": issue},
    }
    return {"object": "page", "id": page_id,
            "parent": {"data_source_id": source}, "properties": properties}


class FakeHTTP:
    def __init__(self, issue=None):
        self.calls = []
        self.blocks = {}
        self.comments = []
        self.pages = {
            push.SOURCES["tasks"][0]: [row(push.SOURCES["tasks"][0], "tasks", TASK, issue)],
            push.SOURCES["feature"][0]: [row(push.SOURCES["feature"][0], "features", FEATURE, issue)],
        }

    def request(self, method, url, token, payload=None, headers=None, retry_transient=True):
        self.calls.append((method, url, payload, token))
        if "/data_sources/" in url:
            source = url.split("/data_sources/")[1].split("/")[0]
            return {"results": self.pages[source], "has_more": False}
        if url == f"{push.NOTION_API}/pages/{push.WORK_LOG}":
            return {"object": "page", "id": push.WORK_LOG}
        if "/blocks/" in url and method == "GET":
            page_id = url.split("/blocks/")[1].split("/")[0]
            return {"results": self.blocks.get(page_id, []), "has_more": False}
        if "/blocks/" in url and method == "PATCH":
            page_id = url.split("/blocks/")[1].split("/")[0]
            block = payload["children"][0]
            self.blocks.setdefault(page_id, []).append({
                "id": f"block-{len(self.blocks.get(page_id, []))}",
                "paragraph": {"rich_text": [
                    {"plain_text": part["text"]["content"]}
                    for part in block["paragraph"]["rich_text"]
                ]}
            })
            assert not retry_transient
            return {"results": self.blocks[page_id]}
        if "/issues/18/comments" in url:
            if method == "GET":
                return self.comments
            self.comments.append({"body": payload["body"]})
            assert not retry_transient
            return {"id": 7}
        if url == f"{push.GITHUB_API}/repos/{push.ORG_REPOSITORY}/issues/18":
            return {"html_url": ISSUE, "node_id": "I_18"}
        raise AssertionError((method, url))


def plan(tasks=None, features=None, summary="Added typed creator brand facts to the local assistant."):
    return {"before": BEFORE, "after": AFTER, "summary": summary,
            "tasks": [TASK] if tasks is None else tasks,
            "features": [FEATURE] if features is None else features}


def test_catalog_reads_only_live_tasks_and_features():
    api = FakeHTTP(ISSUE)
    catalog = push.candidates(api, "notion-secret")
    assert catalog == {
        "tasks": [{"page_id": TASK, "title": "T07 Set up creator brand facts",
                   "feature_ids": "M3", "issue_url": ISSUE}],
        "features": [{"page_id": FEATURE, "title": "M3 Brand memory",
                      "feature_ids": "M3", "issue_url": ISSUE}],
    }
    assert all(call[0] == "POST" and "/data_sources/" in call[1] for call in api.calls)


@pytest.mark.parametrize("change", [
    {"before": AFTER}, {"after": BEFORE}, {"summary": "Feature complete and approved."},
    {"tasks": ["unknown"]}, {"features": ["unknown"]}, {"tasks": [TASK, TASK]},
    {"summary": "Short"}, {"summary": "Code changed https://example.com in the app."},
])
def test_invalid_agent_output_rejected(change):
    catalog = push.candidates(FakeHTTP(), "notion")
    with pytest.raises(push.SyncError):
        push.validate_review(json.dumps({**plan(), **change}), BEFORE, AFTER, catalog)


def test_agent_review_is_read_only_without_tracker_tokens():
    catalog = push.candidates(FakeHTTP(), "notion")
    captured = []

    def runner(argv, **kwargs):
        captured.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout=json.dumps(plan()), stderr="")

    with patch.object(push, "diff", return_value=("diff --git a/x b/x\n+x", False)):
        with patch.dict(push.os.environ, {"GH_PROJECT_TOKEN": "hidden", "NOTION_TOKEN": "hidden"}):
            result = push.review(BEFORE, AFTER, catalog, "copilot-token", runner)
    assert result == plan()
    argv, kwargs = captured[0]
    assert "--available-tools=read" in argv
    assert "--no-custom-instructions" in argv
    assert "diff --git" in argv[argv.index("-p") + 1]
    assert kwargs["env"]["COPILOT_GITHUB_TOKEN"] == "copilot-token"
    assert "GH_PROJECT_TOKEN" not in kwargs["env"] and "NOTION_TOKEN" not in kwargs["env"]


def test_truncated_diff_requires_explicit_excerpt_disclosure():
    catalog = push.candidates(FakeHTTP(), "notion")
    with patch.object(push, "diff", return_value=("+code", True)):
        with pytest.raises(push.SyncError, match="excerpt"):
            push.review(BEFORE, AFTER, catalog, "copilot-token",
                        runner=lambda *a, **kw: SimpleNamespace(
                            returncode=0, stdout=json.dumps(plan()), stderr=""))


def test_unmatched_push_still_writes_work_log_once():
    api = FakeHTTP()
    catalog = push.candidates(api, "notion-secret")
    unmatched = plan(tasks=[], features=[])
    with patch.object(push, "add_to_project", side_effect=AssertionError("no issues")):
        first = push.apply(api, "notion-secret", "github-secret", BEFORE, AFTER,
                           unmatched, catalog)
        second = push.apply(api, "notion-secret", "github-secret", BEFORE, AFTER,
                            unmatched, catalog)
    assert first["work_log_appended"] is True
    assert second["work_log_appended"] is False
    assert first["notion_rows_updated"] == {"tasks": 0, "features": 0}
    assert list(api.blocks) == [push.WORK_LOG]
    assert len(api.blocks[push.WORK_LOG]) == 1
    log_text = "".join(part["plain_text"] for part in
                       api.blocks[push.WORK_LOG][0]["paragraph"]["rich_text"])
    assert f"range {BEFORE[:12]}..{AFTER[:12]}" in log_text
    assert "tasks: none · features: none" in log_text


def test_matched_rows_and_existing_issue_receive_evidence_without_status_edits():
    api = FakeHTTP(ISSUE)
    catalog = push.candidates(api, "notion-secret")
    added = []

    def add(http, token, node_id):
        added.append((token, node_id))
        return len(added) == 1

    with patch.object(push, "add_to_project", side_effect=add):
        first = push.apply(api, "notion-secret", "github-secret", BEFORE, AFTER,
                           plan(), catalog)
        second = push.apply(api, "notion-secret", "github-secret", BEFORE, AFTER,
                            plan(), catalog)
    assert first == {
        "commit": f"https://github.com/{push.REPOSITORY}/commit/{AFTER}",
        "notion_rows_updated": {"tasks": 1, "features": 1},
        "work_log_appended": True, "project_issues_added": 1,
        "existing_issues_commented": 1,
    }
    assert second["notion_rows_updated"] == {"tasks": 0, "features": 0}
    assert second["existing_issues_commented"] == 0
    assert len(api.blocks[TASK]) == len(api.blocks[FEATURE]) == 1
    assert len(api.blocks[push.WORK_LOG]) == len(api.comments) == 1
    log_text = "".join(part["plain_text"] for part in
                       api.blocks[push.WORK_LOG][0]["paragraph"]["rich_text"])
    assert "T07 Set up creator brand facts" in log_text
    assert "M3 Brand memory" in log_text
    assert all(call[0] != "PATCH" or "/pages/" not in call[1] for call in api.calls)
    assert added[0] == ("github-secret", "I_18")


def test_changed_row_aborts_before_any_write():
    api = FakeHTTP(ISSUE)
    catalog = push.candidates(api, "notion-secret")
    api.pages[push.SOURCES["tasks"][0]][0]["properties"]["Task"]["title"][0]["plain_text"] = "Changed title"
    with pytest.raises(push.SyncError, match="changed since agent review"):
        push.apply(api, "notion-secret", "github-secret", BEFORE, AFTER, plan(), catalog)
    assert not api.blocks and not api.comments


def test_only_allowlisted_issue_urls_can_receive_comments():
    api = FakeHTTP("https://github.com/elsewhere/project/issues/18")
    catalog = push.candidates(api, "notion-secret")
    with patch.object(push, "add_to_project", side_effect=AssertionError("unknown issue")):
        result = push.apply(api, "notion-secret", "github-secret", BEFORE, AFTER, plan(), catalog)
    assert result["existing_issues_commented"] == 0
    assert result["notion_rows_updated"] == {"tasks": 1, "features": 1}


def test_fast_forward_push_range_required():
    with patch.object(push.subprocess, "run", return_value=SimpleNamespace(returncode=1)):
        with pytest.raises(push.SyncError, match="fast-forward"):
            push.check_range(BEFORE, AFTER)
    with pytest.raises(push.SyncError, match="40-character"):
        push.check_range("invalid", AFTER)
