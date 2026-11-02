# Web interface: user stories

- Catalogue: the page every feature is shown and tested in (no separate star rating)
- Drafting lead: Omar
- Status: done

Code: [`web/sensai_web/`](https://github.com/OmarCodes022/Sensai/tree/main/web/sensai_web/) (stdlib HTTP server, NDJSON streams) and its static page.
Contract: [`web/web-ui.md`](https://github.com/OmarCodes022/Sensai/blob/main/web/web-ui.md).

## Story 1: Do my whole week in one page

As Nadia, the creator of Serein Studio, I want every Sensai feature in one page on my computer, so
that I can prepare my week without learning terminal commands.

Acceptance criteria:
1. `sensai-web qwen2.5` serves the page on 127.0.0.1 only; chat replies stream as they are written.
2. The chat, personas, sessions, campaign, brand facts, documents, tools, schedule and safety pages work
   with the same rules as the terminal (guardrails, approvals, document search, export).
3. The page is in English or French, and every string exists in both.

Tests: `tests/unit/web/` (one file per surface), `tests/unit/web/test_e2e_week.py` (the whole week).

## Story 2: Stay in control of what runs and what leaves my computer

As Nadia, I want to approve what runs, stop a reply at any time and know that nothing is sent, so that
I trust a tool that drafts in my name.

Acceptance criteria:
1. Every Python run and MCP tool call shows an approval card with the code or arguments; the timer
   pauses while I decide; Stop ends a reply, a team, a weekly run or a summary without saving it.
2. Only one tab talks to Sensai at a time; another tab gets "Open in another tab" with a takeover.
3. No page or route sends, publishes or shares anything: exports are files on this computer.

Tests: `tests/unit/web/test_chat.py` (approvals, stop), `tests/unit/web/test_api.py` (tab lock, host
checks), `tests/unit/web/test_e2e_week.py` (no outgoing call, no share route).

Measured on 2026-11-01 with `qwen2.5`: every feature in the README table was used in the page in one
session (see the [keynote checklist](../keynote-checklist.md)).
