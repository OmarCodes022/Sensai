# Main push code review and evidence sync

`.github/workflows/sync-merge-evidence.yml` runs on **every push to personal
`main`**, including a merged PR. It does not run on PR close separately, so
one merge causes one code-review run. The personal repo's other workflow
(`personal-main-mirror.yml`) runs PR/push tests and optionally mirrors `main`
to Epitech; **the two workflows are independent**. Evidence sync does not
wait for Epitech mirroring, and the mirrored Epitech copy skips its jobs.

When enabled, this workflow checks out trusted personal `main` with full
history, checks that the event's before/after commits form a fast-forward
range on `main`, runs unit tests, reads existing Notion Delivery tasks and
Feature tracker row titles/IDs, and gives a bounded diff and that metadata
to a read-only Copilot CLI review. Direct pushes need no PR or linked issue.
The agent picks relevant **existing** rows and writes a short summary to a
validated JSON plan; it does not receive Project/Notion write credentials.
A separate deterministic step re-reads and validates those rows, then appends
evidence to matched task/feature pages and **always** appends a code-change
entry to the work log, even if no row matches. When a matched row links an
existing GitHub issue, the writer also adds that issue to the organization
Project if missing and posts an idempotent evidence comment. It never creates
issues, rewrites requirements, or changes status/completion fields. All
entries say *code landed, not verified*. An agent match is a suggestion of
relevance, not proof of accepted feature completion.

With activation off, pushes produce an explicit notice and **no tracker
writes**. Manually replay a historical main push from Actions →
**Review main pushes and sync evidence** → **Run workflow** by supplying the
exact 40-character `before` (exclusive) and `after` (inclusive) commit SHAs.
The range must still be reachable from `main`. Replays detect existing
work-log, row and issue evidence for the ending commit.

## One-time configuration

Personal-repo GitHub Actions is available; the separate Epitech organization's
Actions budget still prevents its runners from starting. This workflow does
not require those runners. Before enabling writes, set the following secrets
on **OmarCodes022/Sensai**, not on the Epitech repo:

1. Set Actions repository secret `GH_PROJECT_TOKEN` with write access to the
   organization **Sensai 67** Project (number 269, ID
   `PVT_kwDODOAw1s4BkNJr`) and **Issues read/write** access to the Epitech
   repository if its existing issues are linked on Notion rows. If linking
   personal issues too, it also needs Issues read/write in the personal repo.
   Authorize the credential for the organization (including SSO or token
   approval if required). A classic PAT needs `project` and `repo` scopes
   for the private organization issue access; a fine-grained credential
   needs the equivalent Project and Issues permissions. Use a dedicated
   minimally privileged credential.
   `EPITECH_PUSH_TOKEN` is a *different* mirror credential and is **not** a
   substitute for Project and issue write access.
   The workflow's built-in `GITHUB_TOKEN` cannot be relied on for editing an
   organization Project. GitHub's [Project API guide][project-api] requires
   `project` scope for classic-PAT Project mutations or an authorized GitHub
   App installation token.
2. Create a **Notion internal integration**, enable read, update, and insert
   content capabilities, and explicitly share the Epitech **Feature tracker**
   and **Delivery tasks** databases, plus the **Work log and evidence** page,
   with it. The old merged-PR script also uses Roadmap and Stories by feature,
   but the main-push review only updates tasks, features and the work log.
   Save its integration secret as
   Actions repository secret `NOTION_TOKEN`. Do **not** use or store a personal
   Notion OAuth token; do not put tokens in source, PR bodies, logs, or vars.
3. Allow Copilot CLI billed to the personal account so the workflow's built-in
   `GITHUB_TOKEN` can make Copilot requests (`copilot-requests: write`), **or**
   set the repository secret `COPILOT_TOKEN` to a fine-grained PAT with **Copilot
   Requests** permission for an authorized Copilot seat. The CLI accepts
   `COPILOT_GITHUB_TOKEN` (which this workflow sets from `COPILOT_TOKEN`, or
   falls back to `GITHUB_TOKEN`). Classic PATs are **not** supported for
   Copilot CLI. The Copilot **step** receives no Notion or Project token;
   Notion read and deterministic write steps use step-scoped credentials.
   If neither authentication path is authorized, the workflow fails
   **before tracker writes**.
   See [GitHub's Actions authentication instructions][copilot-actions-auth].
4. Existing `GitHub issue` (Delivery tasks) and `Issue URL` (Feature tracker)
   fields may link an actual issue in either
   `EpitechPGE3-2026/G-AIA-500-STG-5-1-sensai-1` or
   `OmarCodes022/Sensai`. Only those exact URLs on agent-selected rows may
   be used for existing-issue comments/Project membership. The writer
   verifies the issue with GitHub before any change; it never guesses an
   issue number from a feature ID, commit message or PR body. A missing
   issue link **does not prevent Notion row and work-log evidence**.

5. Only after the credentials and personal issue links are ready, set the
   nonsecret repository Actions variable `SENSAI_EVIDENCE_SYNC_ENABLED` to
   `true`. This is independent of `EPITECH_MIRROR_ENABLED`. A manual replay
   with an unset variable reports disabled and does not write; enabling
   without working secrets fails rather than reporting a successful sync.

Missing secrets, Copilot failures, invalid/force-pushed commit ranges,
partial pagination or API errors fail the workflow; inspect Actions and
replay the same range after fixing configuration. API failures never log
credential values or response bodies. Ambiguous failures on Project item
additions, issue comments or Notion appends fail instead of blindly
repeating non-idempotent writes; replay checks existing membership,
comments and evidence blocks. A multi-commit push receives **one** review
for its before→after diff.

## What is (and is not) synchronized

The writer appends a commit-linked paragraph to each selected existing
Delivery task and Feature tracker page. It also appends a summary to the
existing Work log and evidence page **on every reviewed push**, even with
zero task/feature/issue matches. It preserves properties, owner, scope,
status, dependencies and acceptance criteria. If a matched row already
links a verified existing issue, the writer adds that issue to **Sensai 67**
if absent and posts a commit-linked comment on the issue. It cannot create
issues, edit their titles/bodies/statuses or infer new Notion rows.

**A merged PR is not proof that a feature is fully implemented, accepted,
tested, or approved.** The sync never sets Project Status or Notion statuses
(`Implemented`, `Verified`, `Approved`, `Done`, etc.). Native Project
automations, if configured separately, may still act on added/closed issues;
review those rules independently. In Project 269, Status field
`PVTSSF_lADODOAw1s4BkNJrzhi-kII` is not written: existing `Done` items
(including B1) are not duplicated or reset. In particular, undecided A3/epics/optional
features retain their manual decisions. The GitHub stage completes before
Notion writes begin; a failed Notion stage may leave an issue comment or
Project addition in place. Replay after repairing the failure. Test locally
with `python -m pytest -q tests/unit` rather than activating live writes
just to test.

## Required, machine-validated Copilot CLI review

Every enabled push starts headless `@github/copilot` via `copilot -p ...
--no-ask-user -s`. The review receives only a bounded before→after code diff
and existing Notion task/feature titles, IDs and issue URLs, with no Notion or
Project credentials. It cannot use shell or write tools. Its single JSON
object must match both SHAs and contain a bounded plain-text summary plus at
most 10 existing task and 10 existing feature page IDs from the read-only
metadata. The writer re-reads the rows and rejects changed or unknown
records before any writes. The review output is never allowed to choose
statuses or invent destinations. If the diff is truncated, the prompt
requires the summary to say it covers only an excerpt.

GitHub [documents headless Actions invocation][copilot-actions], [authentication
precedence and PAT support][copilot-reference], and [recommends gh-aw for its
broader guardrails][copilot-actions]. This workflow uses direct CLI rather than
gh-aw to keep a strict read-only AI stage and deterministic, testable writes.
The CLI step receives only its Copilot authentication token (no Project or
Notion token); candidate metadata and the JSON plan are kept in the
runner's temporary directory, not committed or uploaded as artifacts. The
writer validates references and writes deterministically.
The summary is not a test result, feature acceptance or approval.

[copilot-actions]: https://docs.github.com/en/copilot/how-tos/copilot-cli/automate-copilot-cli/automate-with-actions
[copilot-actions-auth]: https://docs.github.com/en/copilot/how-tos/copilot-cli/use-copilot-cli-in-actions
[copilot-reference]: https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-command-reference
[project-api]: https://docs.github.com/en/issues/planning-and-tracking-with-projects/automating-your-project/using-the-api-to-manage-projects#authentication
[notion-page]: https://developers.notion.com/reference/patch-page
[notion-blocks]: https://developers.notion.com/reference/patch-block-children
