#!/usr/bin/env python3
"""Synchronize a merged PR's linked issues to the Sensai Project and Notion."""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

REPOSITORY = "OmarCodes022/Sensai"
PROJECT_ID = "PVT_kwDODOAw1s4BkNJr"
ORG = "EpitechPGE3-2026"
SOURCES = {
    "feature": ("8f440ee3-383d-4f9a-8995-cc4c85c14291", "Issue URL", ("PR URL", "Evidence URL")),
    "roadmap": ("4deee045-73c7-417e-92e0-6a13347673e4", "GitHub URL", ()),
    "stories": ("2bcf74ed-c637-4ee3-9758-2a843c71955f", "Issue URL", ("Evidence URL",)),
    "tasks": ("20bed6f4-5afe-4162-8ee5-5eca26c8674e", "GitHub issue", ("PR",)),
}
NOTION_VERSION = "2025-09-03"

PR_QUERY = """
query($owner:String!, $name:String!, $number:Int!) {
  repository(owner:$owner, name:$name) {
    pullRequest(number:$number) {
      id number url merged mergedAt baseRefName
      mergeCommit { url }
      closingIssuesReferences(first:100) {
        nodes { id url repository { nameWithOwner } }
        pageInfo { hasNextPage }
      }
    }
  }
}
"""
PROJECT_QUERY = """
query($project:ID!, $content:ID!) {
  project:node(id:$project) {
    ... on ProjectV2 {
      id closed owner { ... on Organization { login } }
    }
  }
  content:node(id:$content) {
    ... on PullRequest {
      projectItems(first:100) {
        nodes { project { id } }
        pageInfo { hasNextPage }
      }
    }
    ... on Issue {
      projectItems(first:100) {
        nodes { project { id } }
        pageInfo { hasNextPage }
      }
    }
  }
}
"""
ADD_ITEM = """
mutation($project:ID!, $content:ID!) {
  addProjectV2ItemById(input:{projectId:$project, contentId:$content}) {
    item { id }
  }
}
"""


class SyncError(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise SyncError("API redirected a credentialed request")


class HTTP:
    def __init__(self, opener=None, sleep=time.sleep):
        self.opener = opener or urllib.request.build_opener(NoRedirect()).open
        self.sleep = sleep

    def request(self, method, url, token, payload=None, headers=None, retry_transient=True):
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            url,
            body,
            method=method,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                **(headers or {}),
            },
        )
        for attempt in range(4):
            try:
                with self.opener(request, timeout=20) as response:
                    return json.load(response)
            except urllib.error.HTTPError as exc:
                # Never print response bodies: services can echo sensitive input.
                if not retry_transient or exc.code not in (429, 500, 502, 503, 504) or attempt == 3:
                    raise SyncError(f"{method} {url}: HTTP {exc.code}") from None
                retry_after = exc.headers.get("Retry-After")
                delay = int(retry_after) if retry_after and retry_after.isdigit() else 2**attempt
                self.sleep(min(delay, 30))
            except (urllib.error.URLError, TimeoutError) as exc:
                if not retry_transient or attempt == 3:
                    raise SyncError(f"{method} {url}: network failure") from None
                self.sleep(2**attempt)
        raise SyncError(f"{method} {url}: retry limit exceeded")


def github(http, token, query, variables):
    result = http.request(
        "POST", "https://api.github.com/graphql", token,
        {"query": query, "variables": variables},
        retry_transient=query != ADD_ITEM,
    )
    if result.get("errors"):
        # GraphQL errors sometimes include untrusted user data. Avoid logging them.
        raise SyncError("GitHub GraphQL rejected the request (check PROJECT_TOKEN scopes and org access)")
    if "data" not in result:
        raise SyncError("GitHub GraphQL returned no data")
    return result["data"]


def merged_pr(http, token, number):
    owner, name = REPOSITORY.split("/")
    data = github(http, token, PR_QUERY, {"owner": owner, "name": name, "number": number})
    pr = (data.get("repository") or {}).get("pullRequest")
    if not pr or not pr["merged"] or pr["baseRefName"] != "main" or not pr["mergedAt"]:
        raise SyncError(f"PR #{number} is not merged into main")
    if pr["number"] != number or pr["url"] != f"https://github.com/{REPOSITORY}/pull/{number}":
        raise SyncError("Unexpected PR identity")
    references = pr["closingIssuesReferences"]
    if references["pageInfo"]["hasNextPage"]:
        raise SyncError("More than 100 linked issues; refusing incomplete synchronization")
    issues = {issue["id"]: issue["url"] for issue in references["nodes"]
              if issue["repository"]["nameWithOwner"] == REPOSITORY}
    for issue_url in issues.values():
        if not re.fullmatch(rf"https://github\.com/{re.escape(REPOSITORY)}/issues/[1-9][0-9]*", issue_url):
            raise SyncError("Unexpected linked issue URL")
    return pr, issues


def add_to_project(http, token, content_id):
    data = github(http, token, PROJECT_QUERY, {"project": PROJECT_ID, "content": content_id})
    project, content = data.get("project"), data.get("content")
    if not project or project.get("id") != PROJECT_ID or project.get("closed") or (
        project.get("owner") or {}
    ).get("login") != ORG:
        raise SyncError("Target organization Project is unavailable or closed")
    if not content or not content.get("projectItems"):
        raise SyncError("PR/issue Project membership is unavailable")
    items = content["projectItems"]
    if items["pageInfo"]["hasNextPage"]:
        raise SyncError("PR/issue belongs to more than 100 Projects; refusing duplicate")
    if any(item["project"]["id"] == PROJECT_ID for item in items["nodes"]):
        return False
    added = github(http, token, ADD_ITEM, {"project": PROJECT_ID, "content": content_id})
    if not (added.get("addProjectV2ItemById") or {}).get("item", {}).get("id"):
        raise SyncError("GitHub did not confirm Project item addition")
    return True


def rows(http, token, source_id):
    cursor = None
    while True:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        result = http.request(
            "POST",
            f"https://api.notion.com/v1/data_sources/{source_id}/query",
            token,
            body,
            {"Notion-Version": NOTION_VERSION},
        )
        if (result.get("request_status") or {}).get("type") == "incomplete":
            raise SyncError(f"Notion source {source_id} returned incomplete results")
        yield from result["results"]
        if not result["has_more"]:
            break
        cursor = result.get("next_cursor")
        if not cursor:
            raise SyncError(f"Notion source {source_id} has no pagination cursor")


def value(page, key):
    prop = page["properties"][key]
    if prop["type"] != "url":
        raise SyncError(f"Notion property {key} must be a URL")
    return prop["url"]


def append_evidence(http, token, page_id, pr_url, evidence_url):
    marker = f"Sensai merge evidence · PR: {pr_url} ·"
    cursor = None
    while True:
        url = f"https://api.notion.com/v1/blocks/{page_id}/children?page_size=100"
        if cursor:
            url += "&start_cursor=" + urllib.parse.quote(cursor, safe="")
        result = http.request("GET", url, token, headers={"Notion-Version": NOTION_VERSION})
        for block in result["results"]:
            text = "".join(part.get("plain_text", "") for part in
                           block.get("paragraph", {}).get("rich_text", []))
            if text.startswith(marker):
                return False
        if not result["has_more"]:
            break
        cursor = result.get("next_cursor")
        if not cursor:
            raise SyncError("Notion block pagination has no cursor")
    block = {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [
            {"type": "text", "text": {"content": marker, "link": {"url": pr_url}}},
            {"type": "text", "text": {"content": " code landed, not verified · "}},
            {"type": "text", "text": {"content": "merge commit", "link": {"url": evidence_url}}},
        ]},
    }
    http.request(
        "PATCH", f"https://api.notion.com/v1/blocks/{page_id}/children",
        token, {"children": [block]}, {"Notion-Version": NOTION_VERSION},
        retry_transient=False,
    )
    return True


def sync_notion(http, token, issue_urls, pr_url, evidence_url):
    counts = {kind: 0 for kind in SOURCES}
    linked = set(issue_urls)
    if not linked:
        return counts
    for kind, (source_id, link_key, writable) in SOURCES.items():
        for page in rows(http, token, source_id):
            if page.get("object") != "page" or page.get("archived") or page.get("in_trash"):
                continue
            link = value(page, link_key)
            if link not in linked:
                continue
            if page["parent"].get("data_source_id") != source_id:
                raise SyncError(f"Unexpected Notion parent in {kind}")
            updates = {}
            for key in writable:
                current = value(page, key)
                target = pr_url if key in ("PR URL", "PR") else evidence_url
                if not current:
                    updates[key] = {"url": target}
                # Non-empty human-maintained links are never overwritten.
            if updates:
                http.request(
                    "PATCH",
                    f"https://api.notion.com/v1/pages/{page['id']}",
                    token,
                    {"properties": updates},
                    {"Notion-Version": NOTION_VERSION},
                )
            if append_evidence(http, token, page["id"], pr_url, evidence_url) or updates:
                counts[kind] += 1
    return counts


def run(http, project_token, notion_token, number):
    pr, issues = merged_pr(http, project_token, number)
    added_issues = sum(add_to_project(http, project_token, issue) for issue in issues)
    added_pr = add_to_project(http, project_token, pr["id"])
    evidence_url = (pr.get("mergeCommit") or {}).get("url") or pr["url"]
    counts = sync_notion(http, notion_token, issues.values(), pr["url"], evidence_url)
    return {
        "pull_request": pr["url"],
        "linked_issues": len(issues),
        "issue_sync": "linked_issues_only" if issues else "no_linked_issues",
        "project_added_pr": added_pr,
        "project_added_issues": added_issues,
        "notion_rows_updated": counts,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pr", type=int, required=True, help="Merged pull request number")
    args = parser.parse_args()
    try:
        if args.pr < 1:
            raise SyncError("PR number must be positive")
        project_token = os.environ.get("GH_PROJECT_TOKEN")
        notion_token = os.environ.get("NOTION_TOKEN")
        if not project_token or not notion_token:
            raise SyncError("GH_PROJECT_TOKEN and NOTION_TOKEN must both be configured")
        result = run(HTTP(), project_token, notion_token, args.pr)
        summary = json.dumps(result, sort_keys=True)
        print(summary)
    except (SyncError, KeyError, TypeError, ValueError) as exc:
        # Only locally constructed errors are surfaced; never include raw API responses.
        print(f"Merge evidence sync failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
