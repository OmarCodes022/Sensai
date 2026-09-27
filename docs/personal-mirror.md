# Personal main: review, tests, mirror, and evidence

`OmarCodes022/Sensai` is the source repository. Epitech
`G-AIA-500-STG-5-1-sensai-1` is a **main-only destination**.

1. **Getting into personal `main`:** Other contributors must open a PR,
   receive one approval from someone with write access, and pass the GitHub
   Actions `unit-tests` check on an up-to-date branch. New commits dismiss
   prior approvals. The `unit-tests` check is pinned to GitHub Actions, not
   an arbitrary commit status. Non-admins cannot push directly or merge an
   unapproved/failing PR. Omar is currently the only administrator; he can
   bypass review/checks or push directly. Adding another admin gives them
   the same bypass. This branch rule applies only to personal `main`.
2. **Every personal `main` push:** `.github/workflows/personal-main-mirror.yml`
   runs unit tests and, independently, invokes the AWS Lambda mirror using
   GitHub OIDC. The mirror does **not** wait for post-push tests: an admin's
   direct push is mirrored even if those tests fail. A failed unit-test job
   still makes the workflow red. PR runs do not mirror.
3. **Epitech mirror:** Lambda fetches the current personal and Epitech
   `main` branches and fast-forwards Epitech only if its history permits.
   A run for an older, superseded push does nothing; the newer push's run
   handles the latest head. The enabled one-minute EventBridge timer retries
   independently if a GitHub invocation is missed or fails. Both paths use
   the same Lambda and only push `main`: no force pushes, tag copying,
   branch deletion, or Epitech Actions runner is required.
4. **Project/Notion:** `.github/workflows/sync-merge-evidence.yml` separately
   starts on each personal `main` push (direct or merged PR), not on Epitech.
   It does **not** wait for mirror success. It is currently disabled:
   `SENSAI_EVIDENCE_SYNC_ENABLED` is unset and the required Notion,
   GitHub Project, and Copilot credentials are not configured. Its green
   inactive notice is **not** a completed sync. Activation is documented in
   [merge-evidence-sync.md](merge-evidence-sync.md).

The two repositories cannot update atomically: personal `main` moves first,
then the Lambda invocation normally catches Epitech up. If Epitech receives
independent commits, rejects the push, or AWS/GitHub is unavailable, the
branches can remain different. Lambda raises an error instead of rewriting
Epitech history; inspect GitHub Actions and CloudWatch, resolve the blocker,
and retry. No application release or deployment is performed.

## AWS operation

The `eu-west-3` Lambda `sensai-main-mirror` runs a Git/OpenSSH ECR image.
The personal `main` OIDC role may **invoke this function only**; it cannot
read its SSH secret. The Lambda role can read only its dedicated Secrets
Manager secret and write its log stream. The user explicitly authorized
storing their existing personal GitHub SSH key there. Replacing it with
an independently authorized, dedicated key would narrow the blast radius.
GitHub's SSH host key is pinned, and temporary key files are removed after
each invocation. `AWS_MIRROR_ENABLED=true` enables the GitHub invocation;
the EventBridge schedule is controlled separately with Terraform.

Infrastructure and the CodeBuild image builder are defined in
`infra/aws-mirror/`. Build a reviewed repository commit with CodeBuild,
obtain its immutable ECR digest, then apply Terraform with
`-var="image_uri=<ECR digest URI>" -var="enable_schedule=true"`.
Changes to the Lambda code are **not** automatically deployed. Terraform
state is local and ignored by Git; protect and back it up. The ECR
repository was created separately and is not destroyed by Terraform.
Provisioning used the account-root profile; use a least-privileged IAM
identity for future maintenance.

Lambda logs are retained for 14 days. Its CloudWatch error alarm is
visible but has **no notification destination**; configure an alarm action
if proactive alerts are needed. AWS Lambda, ECR, Secrets Manager, and logs
may incur charges. The old Actions `EPITECH_PUSH_TOKEN` and
`EPITECH_MIRROR_ENABLED` flag were retired. For an authorized manual
fast-forward from the personal checkout, use
`git fetch origin main && git push epitech refs/remotes/origin/main:refs/heads/main`.
