# Prompt comparison: dated prompt versions

This folder covers Prompt Versioning (A4 in the subject catalogue) in its
minimal form: system prompts are kept as dated files, and one script runs a
controlled comparison of two of them on the same questions.

| Path | Content |
| --- | --- |
| [`versions/`](versions/) | Dated system prompt versions, one file each |
| [`questions.txt`](questions.txt) | Default questions about the fictional Serein Studio brand |
| [`compare.py`](compare.py) | Sends every question to both prompts and writes a Markdown report |

There is no version database and no new `sensai` option: a version is a file.

## Add a version

Copy the latest version, edit it, and save it as `versions/YYYY-MM-DD-<short-name>.txt`.
Never edit an existing version file; add a new one instead.
`versions/2026-10-20-original.txt` is a copy of the packaged prompt
(`src/sensai/chat/system_prompt.txt`).

## Run a comparison

From the repository root, with Ollama running:

```bash
.venv/bin/python evals/prompt_compare/compare.py \
  evals/prompt_compare/versions/2026-10-20-original.txt \
  evals/prompt_compare/versions/<new-version>.txt \
  --model gemma3:1b
```

Options: `--model` (default `SENSAI_MODEL`), `--host` (default `OLLAMA_HOST`),
`--questions FILE` (one question per line, `#` for comments) and
`--output PATH`. Timeout and context length come from the same `.env`
settings as the CLI.

Each question is sent to prompt A, then prompt B, as a fresh conversation
(system prompt + question, no history). A failed request is recorded in the
report and the run continues. Exit code: 0, 1 if every request failed, 2 for
bad arguments (no model, missing or empty file).

## Read the report

The report is saved to `prompt-reports/compare-<date-time>.md` (git-ignored)
and its path is printed. It contains:

- the date, model, host, questions file and, for each prompt, its path, short
  sha256 and line count;
- a summary per prompt: answered and failed requests, average latency, total
  prompt and output tokens;
- per question, both answers side by side with latency and token counts.

Quality is judged by reading the answers; the script does not score them.

## Roll back

Run the CLI with the older version:

```bash
sensai --prompt evals/prompt_compare/versions/2026-10-20-original.txt
```

or set `SENSAI_PROMPT` to that path in `.env`.

## Limitations

- Model answers vary between runs, so one run is not proof; repeat comparisons.
- Both prompts use the same model and settings; it compares prompts, not models.
- Requires a reachable Ollama server and an installed model.
