import importlib.util
import io
import urllib.error
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "sync_merge_evidence.py"
spec = importlib.util.spec_from_file_location("sync_merge_evidence", SCRIPT)
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)

PR_URL = f"https://github.com/{sync.REPOSITORY}/pull/42"
ISSUE_URL = f"https://github.com/{sync.REPOSITORY}/issues/7"
COMMIT_URL = f"https://github.com/{sync.REPOSITORY}/commit/abcdef"


def test_source_is_personal_repo_and_destination_is_organization_project():
    assert sync.REPOSITORY == "OmarCodes022/Sensai"
    assert sync.ORG == "EpitechPGE3-2026"
    assert sync.PROJECT_ID == "PVT_kwDODOAw1s4BkNJr"


def page(source, kind, issue, **links):
    properties = {sync.SOURCES[kind][1]: {"type": "url", "url": issue}}
    properties["Status"] = {"type": "select", "select": {"name": {
        "feature": "Not started", "roadmap": "Blocked", "stories": "Draft",
        "tasks": "Not started",
    }[kind]}}
    for key in sync.SOURCES[kind][2]:
        properties[key] = {"type": "url", "url": links.get(key)}
    return {
        "object": "page", "id": f"{kind}-{issue.rsplit('/', 1)[-1]}",
        "parent": {"data_source_id": source}, "properties": properties,
    }


class FakeHTTP:
    def __init__(self):
        self.calls = []
        self.project_items = set()
        self.blocks = {}
        self.pr = {
            "id": "PR_42", "number": 42, "url": PR_URL, "merged": True,
            "mergedAt": "2026-09-25T08:00:00Z", "baseRefName": "main",
            "mergeCommit": {"url": COMMIT_URL},
            "closingIssuesReferences": {
                "nodes": [
                    {"id": "ISSUE_7", "url": ISSUE_URL, "repository": {"nameWithOwner": sync.REPOSITORY}},
                    {"id": "ISSUE_elsewhere", "url": "https://github.com/elsewhere/repo/issues/8",
                     "repository": {"nameWithOwner": "elsewhere/repo"}},
                ],
                "pageInfo": {"hasNextPage": False},
            },
        }
        self.pages = {}
        for kind, (source, _, _) in sync.SOURCES.items():
            self.pages[source] = [
                page(source, kind, ISSUE_URL),
                page(source, kind, f"https://github.com/{sync.REPOSITORY}/issues/70"),
            ]

    def request(self, method, url, token, payload=None, headers=None, retry_transient=True):
        self.calls.append((method, url, payload))
        assert token in {"project-secret", "notion-secret"}
        if payload and payload.get("query") == sync.ADD_ITEM:
            assert not retry_transient
        if method == "PATCH" and "/blocks/" in url:
            assert not retry_transient
        if url == "https://api.github.com/graphql":
            query, variables = payload["query"], payload["variables"]
            if query == sync.PR_QUERY:
                return {"data": {"repository": {"pullRequest": self.pr}}}
            if query == sync.PROJECT_QUERY:
                content = variables["content"]
                return {"data": {
                    "project": {"id": sync.PROJECT_ID, "owner": {"login": sync.ORG}, "closed": False},
                    "content": {"projectItems": {
                        "nodes": [{"project": {"id": sync.PROJECT_ID}}] if content in self.project_items else [],
                        "pageInfo": {"hasNextPage": False},
                    }},
                }}
            assert query == sync.ADD_ITEM
            content = variables["content"]
            self.project_items.add(content)
            return {"data": {"addProjectV2ItemById": {"item": {"id": f"ITEM_{content}"}}}}
        if "/data_sources/" in url:
            source = url.split("/data_sources/")[1].split("/")[0]
            return {"results": self.pages[source], "has_more": False}
        if "/blocks/" in url and method == "GET":
            page_id = url.split("/blocks/")[1].split("/")[0]
            return {"results": self.blocks.get(page_id, []), "has_more": False}
        if "/blocks/" in url and method == "PATCH":
            page_id = url.split("/blocks/")[1].split("/")[0]
            paragraph = payload["children"][0]["paragraph"]
            self.blocks.setdefault(page_id, []).append({
                "paragraph": {"rich_text": [
                    {"plain_text": part["text"]["content"]} for part in paragraph["rich_text"]
                ]}
            })
            return {"results": self.blocks[page_id]}
        if "/pages/" in url and method == "PATCH":
            page_id = url.rsplit("/", 1)[-1]
            for source_pages in self.pages.values():
                for row in source_pages:
                    if row["id"] == page_id:
                        row["properties"].update({
                            key: {"type": "url", "url": prop["url"]}
                            for key, prop in payload["properties"].items()
                        })
                        return row
        raise AssertionError((method, url))


def test_project_before_notion_scoped_idempotent_and_status_preserved():
    api = FakeHTTP()
    first = sync.run(api, "project-secret", "notion-secret", 42)
    assert first == {
        "pull_request": PR_URL, "linked_issues": 1,
        "issue_sync": "linked_issues_only",
        "project_added_pr": True, "project_added_issues": 1,
        "notion_rows_updated": {"feature": 1, "roadmap": 1, "stories": 1, "tasks": 1},
    }
    addition = [i for i, call in enumerate(api.calls) if call[2] and call[2].get("query") == sync.ADD_ITEM]
    notion = [i for i, call in enumerate(api.calls) if "api.notion.com" in call[1]]
    assert max(addition) < min(notion)
    assert api.project_items == {"ISSUE_7", "PR_42"}
    for kind, (source, _, _) in sync.SOURCES.items():
        assert api.pages[source][1]["properties"][sync.SOURCES[kind][1]]["url"].endswith("/70")
        assert len(api.blocks[f"{kind}-7"]) == 1
        assert f"{kind}-70" not in api.blocks
        assert api.pages[source][0]["properties"]["Status"]["select"]["name"] == {
            "feature": "Not started", "roadmap": "Blocked", "stories": "Draft",
            "tasks": "Not started",
        }[kind]
    assert api.pages[sync.SOURCES["feature"][0]][0]["properties"]["PR URL"]["url"] == PR_URL
    assert api.pages[sync.SOURCES["feature"][0]][0]["properties"]["Evidence URL"]["url"] == COMMIT_URL
    assert api.pages[sync.SOURCES["tasks"][0]][0]["properties"]["PR"]["url"] == PR_URL
    assert sync.run(api, "project-secret", "notion-secret", 42)["notion_rows_updated"] == {
        "feature": 0, "roadmap": 0, "stories": 0, "tasks": 0,
    }
    assert len(api.blocks["feature-7"]) == 1
    assert sum(call[0] == "PATCH" for call in api.calls) == 7


def test_existing_manual_evidence_is_preserved_while_new_pr_is_appended():
    api = FakeHTTP()
    row = api.pages[sync.SOURCES["feature"][0]][0]
    row["properties"]["PR URL"]["url"] = "https://github.com/earlier/pr"
    row["properties"]["Evidence URL"]["url"] = "https://example.org/manual"
    result = sync.run(api, "project-secret", "notion-secret", 42)
    assert result["notion_rows_updated"]["feature"] == 1
    assert row["properties"]["PR URL"]["url"] == "https://github.com/earlier/pr"
    assert row["properties"]["Evidence URL"]["url"] == "https://example.org/manual"
    assert not any(c[0] == "PATCH" and c[1].endswith("/pages/feature-7") for c in api.calls)
    assert PR_URL in api.blocks["feature-7"][0]["paragraph"]["rich_text"][0]["plain_text"]


def test_replay_recovers_after_ambiguous_append_failure():
    class AmbiguousWrite(FakeHTTP):
        failed = False

        def request(self, method, url, token, payload=None, headers=None, retry_transient=True):
            result = super().request(method, url, token, payload, headers, retry_transient)
            if method == "PATCH" and "/blocks/feature-7/" in url and not self.failed:
                self.failed = True
                raise sync.SyncError("Notion response lost after append")
            return result

    api = AmbiguousWrite()
    with pytest.raises(sync.SyncError, match="response lost"):
        sync.run(api, "project-secret", "notion-secret", 42)
    assert sync.run(api, "project-secret", "notion-secret", 42)["notion_rows_updated"] == {
        "feature": 0, "roadmap": 1, "stories": 1, "tasks": 1,
    }
    assert len(api.blocks["feature-7"]) == 1


def test_notion_pagination_finds_linked_page_on_later_page():
    class Paginated(FakeHTTP):
        def request(self, method, url, token, payload=None, headers=None, retry_transient=True):
            if "/data_sources/" in url:
                self.calls.append((method, url, payload))
                source = url.split("/data_sources/")[1].split("/")[0]
                if payload.get("start_cursor"):
                    assert payload["start_cursor"] == "next"
                    return {"results": [self.pages[source][0]], "has_more": False}
                return {"results": [self.pages[source][1]], "has_more": True, "next_cursor": "next"}
            return super().request(method, url, token, payload, headers, retry_transient)

    result = sync.run(Paginated(), "project-secret", "notion-secret", 42)
    assert result["notion_rows_updated"] == {"feature": 1, "roadmap": 1, "stories": 1, "tasks": 1}


@pytest.mark.parametrize("change", [
    {"merged": False}, {"baseRefName": "develop"}, {"mergedAt": None},
])
def test_unmerged_or_wrong_base_never_writes(change):
    api = FakeHTTP()
    api.pr.update(change)
    with pytest.raises(sync.SyncError, match="not merged into main"):
        sync.run(api, "project-secret", "notion-secret", 42)
    assert all(call[0] == "POST" and "api.github.com" in call[1] for call in api.calls)


def test_missing_linked_issues_does_not_touch_notion_records():
    api = FakeHTTP()
    api.pr["closingIssuesReferences"]["nodes"] = []
    result = sync.run(api, "project-secret", "notion-secret", 42)
    assert result["linked_issues"] == 0
    assert result["issue_sync"] == "no_linked_issues"
    assert api.project_items == {"PR_42"}
    assert result["notion_rows_updated"] == {"feature": 0, "roadmap": 0, "stories": 0, "tasks": 0}
    assert not any("notion.com" in call[1] for call in api.calls)


def test_epitech_issue_reference_does_not_match_personal_notion_evidence():
    api = FakeHTTP()
    org_issue = "https://github.com/EpitechPGE3-2026/G-AIA-500-STG-5-1-sensai-1/issues/7"
    api.pr["closingIssuesReferences"]["nodes"] = [
        {"id": "ISSUE_ORG_7", "url": org_issue,
         "repository": {"nameWithOwner": "EpitechPGE3-2026/G-AIA-500-STG-5-1-sensai-1"}},
    ]
    for kind, (source_id, link_key, _) in sync.SOURCES.items():
        api.pages[source_id][0]["properties"][link_key]["url"] = org_issue
    result = sync.run(api, "project-secret", "notion-secret", 42)
    assert result["linked_issues"] == 0
    assert result["notion_rows_updated"] == {kind: 0 for kind in sync.SOURCES}
    assert api.project_items == {"PR_42"}
    assert not any("notion.com" in call[1] for call in api.calls)


def test_prelinked_pr_or_issue_body_cannot_substitute_for_linked_issue():
    api = FakeHTTP()
    api.pr["closingIssuesReferences"]["nodes"] = []
    api.pr["body"] = "Delivered #18 in PR #42\nIssue: #18"
    feature = api.pages[sync.SOURCES["feature"][0]][0]
    feature["properties"]["PR URL"]["url"] = PR_URL
    roadmap = api.pages[sync.SOURCES["roadmap"][0]][0]
    roadmap["properties"]["GitHub URL"]["url"] = PR_URL
    result = sync.run(api, "project-secret", "notion-secret", 42)
    assert result["issue_sync"] == "no_linked_issues"
    assert result["notion_rows_updated"] == {"feature": 0, "roadmap": 0, "stories": 0, "tasks": 0}
    assert feature["properties"]["Evidence URL"]["url"] is None
    assert not api.blocks
    assert not any("notion.com" in call[1] for call in api.calls)


def test_pagination_limit_fails_before_mutations():
    api = FakeHTTP()
    api.pr["closingIssuesReferences"]["pageInfo"]["hasNextPage"] = True
    with pytest.raises(sync.SyncError, match="More than 100"):
        sync.run(api, "project-secret", "notion-secret", 42)
    assert not api.project_items


def test_wrong_project_owner_blocks_all_writes():
    class WrongProject(FakeHTTP):
        def request(self, method, url, token, payload=None, headers=None, retry_transient=True):
            result = super().request(method, url, token, payload, headers, retry_transient)
            if payload and payload.get("query") == sync.PROJECT_QUERY:
                result["data"]["project"]["owner"]["login"] = "another-org"
            return result

    api = WrongProject()
    with pytest.raises(sync.SyncError, match="Target organization Project"):
        sync.run(api, "project-secret", "notion-secret", 42)
    assert not api.project_items
    assert not any("notion.com" in call[1] for call in api.calls)


def test_github_failure_stops_before_notion():
    api = FakeHTTP()
    def fail(*args, **kwargs):
        return {"errors": [{"message": "secret private data"}]}
    api.request = fail
    with pytest.raises(sync.SyncError, match="GraphQL rejected") as exc:
        sync.run(api, "project-secret", "notion-secret", 42)
    assert "secret private data" not in str(exc.value)


def test_missing_secrets_fails_explicitly_before_network(capsys):
    with patch.dict(sync.os.environ, {"GH_PROJECT_TOKEN": "", "NOTION_TOKEN": ""}):
        with patch.object(sync.sys, "argv", ["sync_merge_evidence.py", "--pr", "42"]):
            assert sync.main() == 1
    assert "GH_PROJECT_TOKEN and NOTION_TOKEN" in capsys.readouterr().err


def test_http_retries_throttling_and_redacts_response():
    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

    attempts = []
    sleeps = []

    def opener(request, timeout):
        attempts.append(request)
        if len(attempts) == 1:
            raise urllib.error.HTTPError(request.full_url, 429, "redact me",
                                         {"Retry-After": "3"}, io.BytesIO(b"SECRET"))
        return Response(b'{"ok":true}')

    result = sync.HTTP(opener=opener, sleep=sleeps.append).request(
        "POST", "https://api.notion.com/v1/test", "secret", {"x": "y"},
    )
    assert result == {"ok": True}
    assert len(attempts) == 2 and sleeps == [3]
    assert attempts[0].get_header("Authorization") == "Bearer secret"


def test_non_retryable_http_error_does_not_expose_body():
    def opener(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 403, "secret", {}, io.BytesIO(b"SECRET"))

    with pytest.raises(sync.SyncError, match="HTTP 403") as exc:
        sync.HTTP(opener=opener).request("POST", "https://api.github.com/graphql", "secret", {})
    assert "SECRET" not in str(exc.value)
