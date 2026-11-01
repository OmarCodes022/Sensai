# Keynote checklist

One creator, one Monday: Nadia, owner of Serein Studio, prepares her week with Sensai in the web page
(`sensai-web qwen2.5`). Every feature of the README table appears where it fits in that session.

## Demo order

1. **Settings and profile**: qwen2.5, the window Sensai picked (Ollama's 4,096 doubled), Nadia's profile.
2. **Campaign → Run the week**: four outputs from brand, DMs and figures; DM02 and DM03 left out.
3. **Approve the posts**, then ask to change P1: the confirm card with before and after.
4. **Chat**: "how do I apply Calm Barrier Cream?" with document sources; an email redacted; "cures
   eczema" blocked; a brand fact remembered; the engagement rate with the calculator.
5. **`/team`** on a post that asks for "cures eczema": researcher, writer, reviewer.
6. **`/think`** on two weeks of likes.
7. **A launch post** where Sensai asks the tone and channel with a form.
8. **Web search** (`/search`) for this winter's trends, with citations.
9. **MCP**: `sensai.weekly_engagement` for the week of 2026-09-21, approved.
10. **Safety → Check an answer**: "It cures eczema in 4 weeks" flagged.
11. **Edit** an earlier message (a new branch), **/context** and **/compact**.
12. **/read** a note and **/save** the reply, then **/export**: private files only.
13. **Schedule**: the drafts made on their own.
14. In a terminal: `SENSAI_CACHE=1` (instant repeat answer) and `SENSAI_EXAMPLES=1` (examples used).

`evals/keynote/demo.py --runs 2` plays steps 2 to 13 through the page's API. On 2026-11-01 with qwen2.5,
**both runs passed all 14 steps** without a crash or a hang (about 3 minutes each). Close the page in the
browser before running it: only one tab talks to Sensai.

## Features

| Feature | Stories | Demo step | Choice / ruled out | Limits | Fallback |
| --- | --- | --- | --- | --- | --- |
| Streaming chat (B1) | [overview 1, 4, 8](overview/user-stories.md) | 4 | Ollama `/api/chat` over HTTP in an isolated worker / no LLM framework, no `ollama` client library | Small models drift from instructions; 120 s per turn | Local |
| Personas (A5) | [overview 1, 2](overview/user-stories.md) | 1, 4 | One catalogue JSON, persona added to the system prompt / fine-tuning per persona | qwen2.5 sometimes answers in JSON (now shown) | Local |
| Saved sessions and profile (M1) | [overview 2, 4, 6](overview/user-stories.md) | 11 | SQLite per creator (stdlib) / one JSON file per session | Plain text on disk | Local |
| Branching and interrupt (X2) | [x2](stories/x2-branching.md) | 11 | A new session up to message N / rewriting in place | Tool rounds before N kept as text | Local |
| MCP (T1) | [t1](stories/t1-mcp-tools.md) | 9 | Own stdio JSON-RPC client, trust per file digest / the MCP SDK, auto-trust | stdio only, 30 s per call; `uvx` servers download on first run | Use the local `sensai.mcp_server`; record the `uvx` time server |
| Tools (calculator, Python, T2) | [overview 3, 5, 6, 7](overview/user-stories.md) | 4 | JSON tool block parsed from the reply / Ollama's native tool API (model-dependent) | The sandbox stops runaway code, not malicious code; qwen2.5 sometimes asks instead of fixing its code | Local |
| Step-by-step reasoning (A1) | [overview 7, 8](overview/user-stories.md) | 6 | Bounded plan, act, check, revise with a structured check / unbounded ReAct | 20-50 s; messy text after a failed tool call | Local |
| Scheduled drafts (X5) | [x5](stories/x5-scheduling.md) | 13 | In-process scheduler thread / system cron (OS-specific) | Runs again at each server start; drafts only | Local |
| Private export (X3) | [x3](stories/x3-private-export.md) | 12 | Guardrail-checked JSON and Markdown, written atomically / PDF (one more dependency) | No PDF | Local |
| Web search (T3) | [t3](stories/t3-web-search.md) | 8 | Brave API with a key, DuckDuckGo HTML without / scraping Google | Needs the network; DuckDuckGo throttles | **Record the step** |
| Questions and forms (X4) | [x4](stories/x4-questions-and-forms.md) | 7 | `ask_user` tool with typed questions / free-text follow-up | The model has to decide to ask | Local |
| Weekly campaign document (M4, T5, A3) | [m4](stories/m4-campaign-document.md), [t5](stories/t5-structured-output.md), [a3](stories/a3-human-in-the-loop.md) | 2, 3 | Schema-forced JSON edits through Ollama's `format`, confirm card for approved sections / free-text editing | A reworded claim is refused: ask again | Local |
| Team of agents (A2) | [a2](stories/a2-team-of-agents.md) | 5 | Three agents with separate inputs / one prompt with three roles, personas | 17-45 s; the reviewer sometimes never approves (shown as disagreement) | Local |
| Semantic cache (A6) | [a6](stories/a6-semantic-cache.md) | 14 | Embedding cosine within a scope hash, first question only / exact match, Redis | Plain-text file; only a session's first question | Local |
| Picked examples (A7) | [a7](stories/a7-picked-examples.md) | 14 | Embedding-picked few-shot turns, never stored / DSPy-style optimization | Shapes the format, not the facts | Local |
| Weekly run (T45) | [t45](stories/t45-weekly-run.md) | 2 | One structured call per output with the campaign checks; report figures in code / one big prompt | 20-45 s; needs the four input files | Local |
| File access (T4) | [t4](stories/t4-file-access.md) | 12 | `.sensai/settings.json` allow and deny rules like Claude Code / a chroot | No symlinks, no listing | Local |
| Guardrails (EV2) | [ev2](stories/ev2-guardrails.md) | 4 | Patterns by data class plus the claims register, checked line by line as the reply streams / an LLM moderator (slow, unreliable at 7B) | Paraphrased claims can pass (the campaign wording check catches some) | Local |
| Brand facts memory (M3) | [m3](stories/m3-fact-sheet.md) | 4 | SQLite facts with `save_fact` / `delete_fact` tools / free-form memory summaries | The model decides when to save | Local |
| Advanced document search (R2) | [r2](stories/r2-advanced-rag.md) | 4 | Product and newest-sheet filter, model rerank 0-10, threshold 6 / a cross-encoder (not in Ollama) | About 8 s more per search | `SENSAI_RAG=basic` |
| Answer scoring (EV1) | [ev1](stories/ev1-answer-scoring.md) | 10 | LLM judge, faithfulness from statement labels, planted check / the RAGAS library (a framework) | A 7B judge mislabels some quotes | Local |
| Brand document search (R1) | [r1](stories/r1-brand-document-search.md) | 4 | nomic-embed-text and a SQLite vector index / Chroma, FAISS | Small corpus | Local |
| Long conversations (M2) | [m2](stories/m2-context-budget.md) | 1, 11 | Summarize the oldest messages at 80%, keep the last 4; window from Ollama, doubled at 4,096 / truncation | A summary costs one request; the 2,000-token instructions | Local |
| Web interface | [web](stories/web-interface.md) | all | Stdlib HTTP server, NDJSON streams, plain ES modules / Flask, FastAPI, a React build | One tab at a time, localhost only | The terminal for every feature |

Every feature passed in the demo runs. To do before the keynote: record step 8 (web search) and, if
it is shown, the `uvx` time server for MCP; run `evals/keynote/demo.py --runs 2` on the keynote machine.

## Honest assessment (closing slide)

- **Works well**: the whole week in one session, with every claim checked against the brand file, private
  data redacted before the model, approvals before anything runs, and nothing ever sent or published.
- **Limits**: a 7B local model drifts (JSON answers, rewording claims, asking instead of fixing code);
  regex guardrails miss paraphrases; the judge is noisy; long replies need the 8,192-token window.
- **Would do differently**: a larger local model or a dedicated small judge; claims checked semantically
  (embeddings) as well as by wording; the weekly run as the opening screen of the page.
