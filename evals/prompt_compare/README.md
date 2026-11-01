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
Never edit an existing version file; add a new one instead. A test checks that the packaged prompt
(`src/sensai/chat/system_prompt.txt`) is one of the versions, so a change to it needs a dated copy.

| Version | What it is |
| --- | --- |
| `2026-10-20-original.txt` | The first packaged prompt |
| `2026-11-01-current.txt` | The packaged prompt today (tools, facts, web search rules added) |
| `2026-11-01-short-answers.txt` | The current one plus: answers under 60 words, one draft unless asked |

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

## Result (2026-11-01, qwen2.5)

`2026-11-01-current.txt` (A) against `2026-11-01-short-answers.txt` (B), the 6 default questions:

| Prompt | Answered | Avg latency | Prompt tokens | Output tokens |
| --- | --- | --- | --- | --- |
| A | 6 | 10.6 s | 3,267 | 833 |
| B | 6 | 15.1 s | 3,447 | 276 |

B writes a third of the text. Its latency is not comparable in this run: the web page was using the
same Ollama at the time. Repeat the run on an idle machine before deciding on speed.

## In the web page

**Settings → Prompt versions** lists the versions. **Use this version** applies one to the next replies
until Sensai restarts (**Back to the original** undoes it); **Compare** asks the same questions to two
versions and shows the answers side by side as they come, then saves the same report.
`SENSAI_PROMPT_VERSIONS` changes the folder the page reads.

## Limitations

- Model answers vary between runs, so one run is not proof; repeat comparisons.
- Both prompts use the same model and settings; it compares prompts, not models.
- Requires a reachable Ollama server and an installed model.
