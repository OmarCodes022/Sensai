# Adversarial testing: manual runner and attack catalogue

This folder holds the project's adversarial-testing material (Adversarial
Testing, EV4 in the subject catalogue). It is **partial**: attacks are run and
judged by hand, and only a few have been run.

| Path | Content |
| --- | --- |
| [`runner.py`](runner.py) | Manual runner: sends your attack turns to the model and records your verdicts |
| [`cases/`](cases/) | Written attack cases, one file per category (`B1-*` IDs target the base chat) |
| [`report.md`](report.md) | Dated status report with the attacks executed so far |

A tester supplies the attack cases, expected behavior, verdicts and analysis.
The runner does not read `cases/` automatically and is not an automated
adversarial suite. It exercises the base chat's `ChatSession` and the real
Ollama client, not ingestion, tools, exports or CLI command parsing (personas,
sessions).

## Run

From the repository root, after installing `requirements.txt` in the project's
virtualenv:

```bash
ollama list
.venv/bin/python evals/adversarial/runner.py gemma3:1b
```

Use an installed model name instead of `gemma3:1b` if needed. Start
`ollama serve` in another terminal if the local server is not running.
The runner otherwise uses the same `.env` settings as the CLI.

For each case:

1. Enter a name, category and expected behavior **before** the model responds.
2. Enter the message over one or more lines, then `/end` on its own line.
   Enter `/end` immediately to test empty input; `//end` inserts a literal
   `/end` line.
3. Choose `y` to add another turn to that case's conversation, or `n` to review.
4. Enter `pass`, `fail` or `inconclusive` and a reason. These are human verdicts,
   not automatic substring checks or model-generated grades.
5. Start the next case, or enter `/quit` at the test-name prompt.

Each new case starts with a fresh conversation. Turns inside one case retain
history, allowing multi-turn tests. A backend failure is reported explicitly
and recorded as inconclusive, never as a successful resistance test. Empty
input rejection can be judged against its declared expected behavior.

Each session produces two files under gitignored `adversarial-reports/`:

- **`.md`: readable report** with pass/fail/inconclusive totals, a test-results
  table, expected behavior, review notes, and every turn's input, response and
  errors. Exact system prompts are expandable and shared by cases using the
  same configuration. Open it in VS Code and use **Open Preview** to read it.
- **`.jsonl`: append-only raw evidence**, kept for reproducibility and tooling.

Default names use readable local time, for example
`t10-2026-10-02_15-41-57.md` and `t10-2026-10-02_15-41-57.jsonl`.
A new run in the same second gets `-2`, `-3`,
etc., without overwriting or mixing runs. No report is created until a case
has been attempted. `--report` chooses your own name and appends if it exists.
For example, `--report adversarial-reports/my-session.jsonl` also generates
`adversarial-reports/my-session.md`. For paths without the `.jsonl` suffix,
the companion appends `.md` to the full filename instead.
The Markdown file is regenerated after each saved case, including previously
recorded cases. Do not edit it manually: keep your verdict reasons in the runner
and write your final analysis separately.
Each record includes the exact system prompt, model tag, host, timeout,
timestamp, expected behavior, all attempted inputs, replies/errors, verdict
and notes. Attempted cases are saved if review or streaming is interrupted;
an unfinished case stays inconclusive. Prompts entered but interrupted before
submission are not model test attempts.

Existing JSONL reports can also be converted without a running Ollama server,
a selected model or a system prompt file:

```bash
.venv/bin/python evals/adversarial/runner.py \
  --render-report adversarial-reports/my-session.jsonl
```

Malformed existing evidence is reported as an error, not silently skipped.
If Markdown generation fails after a case is saved, the runner reports the
failure; the JSONL evidence remains available to regenerate the report later.

Use **synthetic data only**: the reports retain complete inputs and outputs.
The model tag and settings help reproduce the setup, but generated answers can
vary, and an Ollama tag may point to a different model version later. Record
the model digest/version separately when collecting evaluation evidence.

Exit codes: `0` means all recorded cases were manually marked pass; `1` means
a case failed/was inconclusive, or an I/O error occurred; `2` means no cases
were run or arguments were invalid; `130` means interrupted input/session.
None of these establishes coverage of all attacks.

## Change the prompt

The runner uses the packaged default prompt (`src/sensai/chat/system_prompt.txt`)
unless `--prompt` or `SENSAI_PROMPT` names another file. Edit that file, then
restart the runner to load the change.
Its default now describes the creator scope, approved-claim and privacy rules,
untrusted embedded instructions, draft/approval boundaries and honest capability
reporting. It contains no fictional product facts or approved brand claims.
Supply synthetic facts for a case or use a separate prompt when testing a
specific scenario:

```bash
.venv/bin/python evals/adversarial/runner.py gemma3:1b \
  --prompt path/to/test-prompt.txt \
  --report adversarial-reports/my-session.jsonl
```

Prompt instructions are **not** an input sanitizer, classifier, permission
boundary or enforced output gate. Raw content has already reached the model
when it reads the prompt. Enforcement needs a future guardrail; see
[privacy-and-claims.md](../../docs/product/privacy-and-claims.md).

Start with base-chat cases. For brand-specific cases, reuse the versioned
synthetic brand, DM, post and engagement data in
[`tests/fixtures/`](../../tests/fixtures/), and extend the cases and report as
features become runnable.
