# Merged PR evidence sync

`.github/workflows/sync-merge-evidence.yml` runs unit tests against the PR
merge ref when a PR is opened or updated; these pre-merge checks have no
Project or Notion credentials and do not synchronize anything. When a PR is
**merged into `main`**, unit tests run again against trusted `main` before
the evidence sync. The merged-PR workflow can also be replayed from Actions →
**Sync merged PR evidence** → **Run workflow** with `pr_number`. The script independently re-reads the PR
from GitHub and rejects unmerged PRs and other base branches. It checks out
trusted `main` code, not the PR head. Unit tests and a read-only Copilot CLI
summary run separately; only after both succeed does a deterministic job
synchronize Project and Notion. Copilot output **never**
selects tracker records or determines tracker writes.

## One-time configuration

1. Set an Actions repository secret `GH_PROJECT_TOKEN` with access to the
   organization **Sensai 67** Project (number 269, ID
   `PVT_kwDODOAw1s4BkNJr`) and read access to this private repository's PRs and
   issues. For a classic PAT, authorize it for the organization (including SSO
   if required) with `project` and `repo` scopes; alternatively, use an
   authorized GitHub App installation token with organization Projects write
   and repository Pull requests and Issues read permissions. Use a dedicated
   minimally privileged account/token.
   The workflow's built-in `GITHUB_TOKEN` cannot be relied on for editing an
   organization Project. GitHub's [Project API guide][project-api] requires
   `project` scope for classic-PAT Project mutations or an authorized GitHub
   App installation token.
2. Create a **Notion internal integration**, enable read, update, and insert
   content capabilities, and explicitly share the Epitech **Feature tracker**,
   **Roadmap**, **Stories by feature**, and **Delivery tasks** databases with it.
   Save its integration secret as
   Actions repository secret `NOTION_TOKEN`. Do **not** use or store a personal
   Notion OAuth token; do not put tokens in source, PR bodies, logs, or vars.
3. Allow Copilot CLI billed to the organization so the workflow's built-in
   `GITHUB_TOKEN` can make Copilot requests (`copilot-requests: write`), **or**
   set the repository secret `COPILOT_TOKEN` to a fine-grained PAT with **Copilot
   Requests** permission for an authorized Copilot seat. The CLI accepts
   `COPILOT_GITHUB_TOKEN` (which this workflow sets from `COPILOT_TOKEN`, or
   falls back to `GITHUB_TOKEN`). Classic PATs are **not** supported for
   Copilot CLI. The first job has only repository read and Copilot request
   permissions; it receives **no** Project/Notion credentials. If neither
   authentication path is authorized, the job fails **before tracker writes**.
   See [GitHub's organization-policy instructions][copilot-actions-auth].
4. In the feature tracker and stories database, populate `Issue URL` with an
   exact URL such as
   `https://github.com/EpitechPGE3-2026/G-AIA-500-STG-5-1-sensai-1/issues/7`.
   In the roadmap, `GitHub URL` may similarly link an issue; Delivery tasks
   uses `GitHub issue`. Only issues in
   this repository included in the merged PR's GitHub
   `closingIssuesReferences` are considered (for example, a GitHub-linked
   closing reference such as `Closes #18`). A title, label, feature ID,
   prefilled PR URL, commit message, loose issue mention, or `Issue: #18`
   in body text is **not** a validated link in this workflow. Without a
   GitHub-linked issue, only the merged PR is added to the Project; no
   Notion requests or updates are made. The log reports
   `issue_sync: no_linked_issues`.

Missing secrets, Copilot authentication/validation failures, authorization
failures, invalid PRs, partial pagination, or API errors fail the workflow;
inspect the Actions failure and replay the PR after fixing configuration.
The sync prints non-sensitive counts (no tokens or raw API errors).
Transient failures on reads and idempotent property
updates retry with bounded backoff. Ambiguous failures on Project item additions
or Notion block appends fail rather than blindly repeating a non-idempotent
write; replays detect existing Project membership and evidence blocks.

## What is (and is not) synchronized

After the Copilot gate, the merged PR and its linked same-repository issues are added as
content items to **Sensai 67** if absent. Existing Project items/fields are
left alone. Next, **only existing Notion rows with exact matching linked issue
URLs**
receive an append-only paragraph linking the merged PR and merge commit,
explicitly labeled *code landed, not verified*. Empty `PR URL` and
`Evidence URL` properties in matching feature rows, empty `Evidence URL`
in matching story rows, or empty `PR` in matching Delivery tasks are filled
once; nonempty values are preserved. Roadmap rows only receive an evidence
paragraph. Other page content, owner,
scope, status, dependencies, and criteria are never rewritten. Later merged
PRs add further evidence paragraphs without overwriting previous links.
Notion does not get new guessed features, stories, or roadmap entries.
The script uses [PATCH page][notion-page] only for listed URL properties and
[append block children][notion-blocks] for evidence; it never replaces a page.

**A merged PR is not proof that a feature is fully implemented, accepted,
tested, or approved.** The sync never sets Project Status or Notion statuses
(`Implemented`, `Verified`, `Approved`, `Done`, etc.). Native Project
automations, if configured separately, may still act on added/closed issues;
review those rules independently. In Project 269, Status field
`PVTSSF_lADODOAw1s4BkNJrzhi-kII` is not written: existing `Done` items
(including B1) are not duplicated or reset. In particular, undecided A3/epics/optional
features retain their manual decisions. The GitHub stage completes before
Notion begins; a failed Notion stage may leave Project additions in place.
Replay safely after repairing the failure. Do not trigger the workflow against
live services just to test it; use `python -m pytest -q
tests/unit/test_copilot_merge_summary.py tests/unit/test_sync_merge_evidence.py`
for the offline mocked suite.

## Required, machine-validated Copilot CLI summary

Every merged PR starts the headless `@github/copilot` CLI via `copilot -p ...
--no-ask-user -s`. The first job fetches the merged PR and first-parent merge
diff with **read-only** repository credentials, passes a bounded excerpt as
untrusted evidence, disables repository custom instructions, and limits CLI
tools to `read` (`--available-tools=read`). It validates a single JSON object
against the exact PR URL, commit SHA, evidence level
`code_landed_not_verified`, and a bounded plain-text summary with no approval
or verification claims. Invalid/unavailable output fails the workflow; the
summary is printed to the job log, **not** passed to the sync job. The second
job independently rereads the PR and uses only linked GitHub/Notion records.
No Copilot-generated text can set Project Status or Notion status.

GitHub [documents headless Actions invocation][copilot-actions], [authentication
precedence and PAT support][copilot-reference], and [recommends gh-aw for its
broader guardrails][copilot-actions]. This workflow uses direct CLI rather than
gh-aw to keep a strict read-only AI stage and deterministic, testable writes.
Because direct CLI can access its job environment, the Copilot job is separate
from—and has no secrets for—the Project/Notion write job. No output artifact
is needed: the validated summary is logged, while the subsequent job rereads
authoritative PR evidence independently.
The summary is not a test run, review, or feature acceptance.

[copilot-actions]: https://docs.github.com/en/copilot/how-tos/copilot-cli/automate-copilot-cli/automate-with-actions
[copilot-actions-auth]: https://docs.github.com/en/copilot/how-tos/copilot-cli/use-copilot-cli-in-actions
[copilot-reference]: https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-command-reference
[project-api]: https://docs.github.com/en/issues/planning-and-tracking-with-projects/automating-your-project/using-the-api-to-manage-projects#authentication
[notion-page]: https://developers.notion.com/reference/patch-page
[notion-blocks]: https://developers.notion.com/reference/patch-block-children
