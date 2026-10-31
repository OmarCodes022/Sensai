# Scheduled drafts

List a few recurring requests in a small JSON file, and Sensai runs them at their interval and
saves each answer as a dated draft. Drafts are only written to disk: nothing is ever posted or
sent.

```bash
cp schedule.example.json schedule.local.json     # yours, not shared (gitignored)
SENSAI_MODEL=qwen2.5 .venv/bin/python -m sensai.schedule schedule.local.json
```

```text
Scheduler started: 2 tasks. Ctrl+C to stop.
[09:00] post-ideas -> drafts/2026-11-02-0900-post-ideas.md
[09:00] dm-themes failed: cannot reach Ollama (will retry in 1440 min)
```

## The tasks file

A JSON list; each task has a `name` (lowercase, dashes), a `prompt`, an `every_minutes` interval
and an optional `persona` (the same ids as the chat):

```json
[{"name": "post-ideas", "prompt": "Propose three post ideas for this week", "every_minutes": 10080, "persona": "redaction"}]
```

A broken file (bad JSON, a missing field, an unknown persona, a duplicate name) is refused
before anything runs.

## How a run works

- Each task runs when the scheduler starts, then every `every_minutes`.
- A run is one chat request with the shared rules and the task's persona, under the usual
  time limit, and the reply goes through the [guardrails](guardrails.md)' check.
- The answer is saved as `drafts/<date>-<time>-<task>.md` with a short header (task,
  persona, model, time). A failed run (Ollama down, missing model, a refused claim) is
  reported, saves nothing, and is retried at the next interval. Ctrl+C stops cleanly.

## In the web interface

When `schedule.local.json` exists (or `SENSAI_SCHEDULE_FILE` points to a file), `sensai-web`
runs the tasks in the background. The **Schedule** page lists each task with its interval, the
time to its next run and its last result, a **Run now** button, and the drafts, which open in a
viewer. `SENSAI_DRAFTS_DIR` changes the folder.
