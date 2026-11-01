# Usage log and statistics

Every model call adds one JSON line to `sensai-log.jsonl` (`SENSAI_LOG` changes the path; empty turns
the log off):

```json
{"time": "2026-11-01T10:34:12+00:00", "kind": "chat", "model": "qwen2.5", "persona": "redaction",
 "question": "My post got 630 likes out of 4200 followers...", "answer": "The engagement rate is 15%.",
 "latency_ms": 2984, "prompt_tokens": 2429, "output_tokens": 155,
 "tools": [{"tool": "calculate", "input": "{\"expression\": \"630/4200 * 100\"}", "ms": 111, "ok": true}],
 "error": null}
```

- `kind` is `chat` (a turn, including `/think` and `/team`), `title` or `summary`.
- `tools` lists every tool the turn used, with its input, duration and success (`[]` without tools).
- `error` is the failure, `cancelled`, `timed out`, or `blocked: <reason>` when the guardrails stopped
  the reply (counted as a refusal, not an error).

```text
$ sensai --stats
Calls: 8   Errors: 0 (0%)   Cancelled: 0   Blocked: 1   Avg latency: 10.0 s   Tokens: 17,564 in / 1,035 out
Kinds: chat 7, title 1
Tools: ask_user 1 call, 0 failed, run_python 1 call, 0 failed, search_docs 1 call, 0 failed

Day          Calls  Avg latency  Errors
2026-11-01       8       10.0 s       0
```

`--stats` needs no model and no Ollama, and says "No data yet" without a log. In the web page, the
**Insights** page shows the same figures, one row per day (with trend lines from two days on), tool
usage and the last ten calls.

The log keeps your conversations in plain text, like the session database. It is in `.gitignore`.
