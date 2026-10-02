# T10 manual test setup

Diana supplies the attack cases, expected behavior, verdicts and analysis.
`scripts/testing/adversarial_test.py` is a runner, not an implemented adversarial suite
or proof that EV4 is complete. It exercises the current B1 `ChatSession` and
real Ollama client, not future ingestion, tools, exports or CLI command parsing.

## Run

From the repository root, after installing `requirements.txt` in the project's
virtualenv:

```bash
ollama list
.venv/bin/python scripts/testing/adversarial_test.py gemma3:1b
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

Reports are append-only JSONL files under gitignored `adversarial-reports/`.
Default names use readable local time, for example
`t10-2026-10-02_15-41-57.jsonl`. A new run in the same second gets `-2`, `-3`,
etc., without overwriting or mixing runs. No report is created until a case
has been attempted. `--report` chooses your own name and appends if it exists.
Each record includes the exact system prompt, model tag, host, timeout,
timestamp, expected behavior, all attempted inputs, replies/errors, verdict
and notes. Attempted cases are saved if review or streaming is interrupted;
an unfinished case stays inconclusive. Prompts entered but interrupted before
submission are not model test attempts.

Use **synthetic data only**: the reports retain complete inputs and outputs.
The model tag and settings help reproduce the setup, but generated answers can
vary, and an Ollama tag may point to a different model version later. Record
the model digest/version separately when collecting evaluation evidence.

Exit codes: `0` means all recorded cases were manually marked pass; `1` means
a case failed/was inconclusive, or an I/O error occurred; `2` means no cases
were run or arguments were invalid; `130` means interrupted input/session.
None of these establishes coverage of all attacks or completion of T10.

## Change the prompt

Edit `prompts/system.txt`, then restart the runner to load the change.
Its default now describes the creator scope, approved-claim and privacy rules,
untrusted embedded instructions, draft/approval boundaries and honest capability
reporting. It contains no fictional product facts or approved brand claims.
Supply synthetic facts for a case or use a separate prompt when testing a
specific scenario:

```bash
.venv/bin/python scripts/testing/adversarial_test.py gemma3:1b \
  --prompt path/to/test-prompt.txt \
  --report adversarial-reports/my-session.jsonl
```

Prompt instructions are **not** an input sanitizer, classifier, permission
boundary or enforced output gate. Raw content has already reached the model
when it reads the prompt. Enforcement remains T38's work; see
[privacy-and-claims.md](../product/privacy-and-claims.md).

Start with B1 cases now. Reuse T06's versioned synthetic data for later
brand-specific cases, and extend the tests/report as features become runnable.
