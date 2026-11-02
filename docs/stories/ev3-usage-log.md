# EV3 Logging & Monitoring Dashboard: user stories

## Story 1: Every exchange recorded

As Nadia, the creator of Serein Studio, I want every exchange with Sensai recorded, so that I can find
what was asked and answered, and how long it took.

Acceptance criteria:
1. Each question and answer is saved with the time, model, persona, latency and token counts.
2. Tools Sensai used, such as web search or the calculator, are recorded with their input, duration and
   result; a turn without tools has `"tools": []`.
3. Failed requests are saved with their error, cancelled ones as `cancelled`, blocked ones with the
   guardrails' reason; title and summary requests have their own kind.

## Story 2: Notice when Sensai gets slower or less reliable

As Nadia, I want to see usage statistics, so that I notice when Sensai becomes slower or less reliable.

Acceptance criteria:
1. `sensai --stats` and the web Insights page show calls, average latency, error rate and tokens.
2. I see one row per day and how often each tool was used and failed.
3. `--stats` works without a chat, a model or Ollama, and says clearly when there is no data.
