# Personal repository and Epitech mirror

`OmarCodes022/Sensai` is public. It was initially populated from the two
branches that existed on the private Epitech repository: `main` and
`ci/merge-evidence-sync-20260925`. Both branches retain their original commit
IDs and history; there were no tags. Old local remote-tracking branches that
no longer exist on GitHub were not copied. Local untracked files are not part
of either repository.

The **personal `main` branch is the working source**. Pull requests and pushes
to personal `main` run unit tests. After tests pass, the workflow attempts a
non-forced fast-forward of Epitech `main` to the exact tested commit. It does
not mirror other branches or tags, delete Epitech refs, or run its jobs in the
Epitech repository. If Epitech `main` advances independently, the push fails
rather than discarding a teammate's work: integrate those commits into
personal `main`, rerun tests, then retry. Epitech branch protection may
require a reviewed PR instead of a direct push; this workflow does not bypass
that rule.

## Activate automatic mirroring

Create a **dedicated fine-grained personal access token** for the Epitech
repository, with repository **Contents: read and write** permission and
organization approval/SSO if required. Do not reuse the GitHub CLI's broad
login token. Store it as an **Actions repository secret**
`EPITECH_PUSH_TOKEN` in `OmarCodes022/Sensai` under Settings → Secrets and
variables → Actions. Never put its value in code, an issue, or chat. This
secret is not available to the read-only test job or pull requests; the
mirror job only runs on personal `main` or a manual run of that branch.

Until the secret is configured, the mirror job fails explicitly and makes no
Epitech changes. A maintainer with write access can perform a one-time
non-forced `git push origin HEAD:refs/heads/main` from a locally tested
personal `main` checkout, if Epitech permits direct pushes. Future personal
pushes still need the secret for automatic mirroring. After configuring it,
manually run **Test and mirror personal main** from Actions on `main` (or rerun
the failed run) and verify that both repositories' `main` commit IDs match.
If the organization rejects the token or a protected branch blocks the
push, request authorization or switch to a PR-based handoff; do not force
push. The Epitech organization's Actions budget does not fund the personal
workflow, but Epitech-only workflows remain blocked until its budget is
restored.

From this local clone, `personal` is the personal remote and `origin` remains
the Epitech remote. Push work to `personal`, not `origin`, when using the
personal repository as the source.
