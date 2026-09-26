# Personal repository and Epitech mirror

`OmarCodes022/Sensai` is public and is the source of truth for `main`.
`EpitechPGE3-2026/G-AIA-500-STG-5-1-sensai-1` is the private destination.
The personal repo was initially populated from the two then-existing Epitech
branches; the four setup commits were later rewritten to remove co-author
trailers. Untracked files are not mirrored.

Personal pushes and PRs run unit tests. An AWS Lambda in `eu-west-3` checks
the public personal `main` once per minute. **Only a passing personal `main`
run** can publish its exact tested commit ID to AWS Systems Manager via GitHub
Actions OIDC. The Lambda skips the push unless that ID is still the current
personal head; it fetches both histories and fast-forwards only Epitech
`main`. No force pushes, other branches, tags, ref deletions, or CI on Epitech
are involved. If Epitech has independent commits or branch protection blocks
the push, Lambda fails and its CloudWatch alarm fires; integrate the divergent
work into personal `main` or resolve branch protection before retrying.
The Lambda does not bypass organization SSH authorization.

As of 2026-09-26 the schedule is enabled. A controlled Lambda invocation
fast-forwarded Epitech `main` to the CI-tested personal SHA
`d32b99a912076ff61a369c1bf33c63dbf42b6b4e`. The user explicitly
authorized storing their **existing personal SSH key** in AWS Secrets
Manager rather than adding a dedicated key; replace it with a dedicated,
authorized key when possible to reduce the impact of a compromised Lambda
role or secret. AWS provisioning used the selected account-root profile;
use a least-privileged IAM identity for future maintenance. Terraform state
is kept locally outside Git and contains resource metadata, not the private
SSH key.

## AWS setup and activation

The infrastructure and implementation are under `infra/aws-mirror/`. It uses
an ECR container (Git and OpenSSH), a Secrets Manager secret for an authorized
GitHub SSH key, a scoped Lambda role, a GitHub OIDC role that can
write only the tested SHA parameter, a one-minute EventBridge rule, 14-day
logs, and an error alarm. The alarm is visible in CloudWatch but does **not**
send notifications until a notification action is configured. The rule starts
disabled. Lambda, ECR storage, Secrets Manager and logging may incur AWS
charges even with the rule disabled; review usage and clean up when unused.
Do not put credentials in Terraform state, this repository, Actions secrets,
chat, container images, or build logs.

1. Use an approved AWS IAM provisioning identity (`AWS_PROFILE`), in Paris
   (`AWS_REGION=eu-west-3`). Create ECR repository `sensai-mirror` there.
   Run `terraform -chdir=infra/aws-mirror init`, then
   `terraform -chdir=infra/aws-mirror apply -target=aws_codebuild_project.image -var="image_uri=..."`.
   Build the exact reviewed personal commit with
   `aws codebuild start-build --project-name sensai-mirror-image --environment-variables-override name=SOURCE_COMMIT,value=<sha>,type=PLAINTEXT`.
   After the build succeeds, obtain its immutable ECR digest URI
   (`.../sensai-mirror@sha256:...`) and run
   `terraform -chdir=infra/aws-mirror apply -var="image_uri=..."`.
   Terraform state is local and ignored by Git; protect and back it up.
2. Put an authorized GitHub SSH private key into the created Secrets Manager
   secret `sensai/mirror/epitech-ssh` (a `SecretString`). **Prefer a new,
   dedicated key:** add its public half in GitHub account settings as an
   authentication key and authorize Epitech SSO if prompted. With the key
   owner's explicit consent, an existing GitHub SSH key may be used instead;
   this extends that personal key's access to the AWS Lambda and raises its
   impact if AWS access is compromised. Never use the unapproved
   `EPITECH_PUSH_TOKEN`, and rotate any copied personal key if AWS is
   compromised. If GitHub refuses the key, request an authorized credential
   instead of working around the policy.
3. Set personal repository Actions variable `AWS_MIRROR_OIDC_ROLE_ARN` to
   Terraform output `ci_role_arn`, then `AWS_MIRROR_ENABLED=true`. Run the
   personal workflow on `main`; confirm the `authorize-aws-mirror` job passed
   and SSM `/sensai/mirror/last-tested-sha` is the exact tested `main` SHA.
4. Invoke `sensai-main-mirror` manually and verify its result says `mirrored`
   or `up_to_date` and both remote `main` SHAs match. Enable the schedule
   with `terraform -chdir=infra/aws-mirror apply -var="image_uri=..." -var="enable_schedule=true"`
   only after that verification. If CI or
   GitHub SSH authorization is not ready, leave it disabled.

The old Actions PAT mirror is retired; `EPITECH_MIRROR_ENABLED=false` and the
old `EPITECH_PUSH_TOKEN` do not activate AWS mirroring. Remove that unused
token when the new mirror is working. In the personal checkout, `origin` is
personal and `epitech` is Epitech. To manually mirror an already-tested
commit if authorized, use
`git fetch origin main && git push epitech refs/remotes/origin/main:refs/heads/main`
(no force).
