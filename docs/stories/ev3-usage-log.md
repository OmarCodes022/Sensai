# EV3 Logging & Monitoring Dashboard: user stories

- Catalogue: EV3 ★★
- Drafting lead: Omar
- Status: done

Code: [`usage_log.py`](https://github.com/OmarCodes022/Sensai/blob/main/src/sensai/usage_log.py) (log lines and statistics), the turn loggers in
[`cli/usage.py`](https://github.com/OmarCodes022/Sensai/blob/main/src/sensai/cli/usage.py) and [`turn.py`](https://github.com/OmarCodes022/Sensai/blob/main/web/sensai_web/turn.py), and the web
Insights page. Guide: [Usage log and statistics](../user-guide/insights.md).

## Story 1: Every exchange recorded

As Nadia, the creator of Serein Studio, I want every exchange with Sensai recorded, so that I can find
what was asked and answered, and how long it took.

Acceptance criteria:
1. Each question and answer is saved with the time, model, persona, latency and token counts.
2. Tools Sensai used, such as web search or the calculator, are recorded with their input, duration and
   result; a turn without tools has `"tools": []`.
3. Failed requests are saved with their error, cancelled ones as `cancelled`, blocked ones with the
   guardrails' reason; title and summary requests have their own kind.

Tests: `tests/unit/test_usage_log.py`, `tests/unit/web/test_insights_web.py`.

## Story 2: Notice when Sensai gets slower or less reliable

As Nadia, I want to see usage statistics, so that I notice when Sensai becomes slower or less reliable.

Acceptance criteria:
1. `sensai --stats` and the web Insights page show calls, average latency, error rate and tokens.
2. I see one row per day and how often each tool was used and failed.
3. `--stats` works without a chat, a model or Ollama, and says clearly when there is no data.

Measured on 2026-11-01 with `qwen2.5`: one keynote demo run logged 8 calls (7 chat, 1 title) with
search_docs, run_python and ask_user; the reply the guardrails blocked was listed as blocked, not as an
error; the Insights page showed the same figures.
