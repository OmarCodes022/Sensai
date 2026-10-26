# M2 Token Budgeting & Semantic Compression — user stories

- Catalogue: M2 ★★ (depends on metrics)
- Drafting lead: Diana
- Reviewer: _to assign_
- Status: draft

Code: [`chat/compression.py`](../../src/sensai/chat/compression.py) (when and how to
summarize), `ContextState`, `_summarize` and `/context` in
[`cli/main.py`](../../src/sensai/cli/main.py).

## How it works

After each completed turn Sensai takes the token count Ollama reported for the
last request of the turn (`prompt_eval_count + eval_count`, via `usage_sink`),
or estimates characters ÷ 4 when Ollama reports none. At 80% of the budget
(`--context-budget`, `SENSAI_CONTEXT_BUDGET`, else `SENSAI_CONTEXT_LENGTH`, else
4096) it asks the model, in one extra request, to summarize every message
between the system prompt and the last 4 messages. Those messages are replaced
by one assistant message starting with `Summary of earlier conversation:`,
which is also saved in the session.

- A tool call and its result are never separated (the cut moves back).
- An earlier summary is kept word for word and the new summary is appended to
  it. Re-summarizing a summary lost the launch date on `gemma3:1b` (see
  measurements).
- A failed, timed out or cancelled summary keeps the full history and prints
  `warning: summary failed, full history kept`.

## Story 1: Keep a long planning session working

As a skincare creator planning a week of posts in one long session, I want
Sensai to condense old messages when the conversation gets long, so that it
keeps working without forgetting my launch details.

Acceptance criteria:
1. When a turn reaches 80% of the budget, Sensai prints
   `Context: <count> / <budget> tokens (<pct>%), summarizing <n> older messages…`.
2. On the next turn it prints the new count, which is lower than before.
3. Facts given early (launch date, product) are still answered correctly after
   several summaries. The system prompt, persona and last 4 messages are
   unchanged, and `/persona` still works.
4. With the default budget, a short chat never triggers a summary.

Tests: `tests/unit/cli/test_context.py`
(`test_summary_near_budget_lowers_count_and_is_reported`,
`test_default_budget_short_chat_never_summarizes`,
`test_persona_kept_and_switchable_after_summary`) and
`tests/unit/chat/test_compression.py` (threshold, cut, tool pairs, verbatim
earlier summary).

Measured on 2026-10-26, `sensai gemma3:1b --context-budget 1500
--operation-timeout 300`, 9 turns planning a week of posts. The first message
was "Our launch is on 14 November and the hero product is Calm Barrier Cream."

| Summary | Count before | Count on next turn | Messages summarized |
| --- | --- | --- | --- |
| 1 | 1,456 (97%) | 1,127 (75%) | 2 |
| 2 | 1,272 (84%) | 1,083 (72%) | 5 |
| 3 | 1,275 (85%) | 1,244 (82%) | 5 |
| 4 | 1,244 (82%) | 1,193 (79%) | 3 |

`/context` at the end: `Budget 1,500   Last turn 1,193 (79%)   Summaries 4
Saved about 600 tokens`. Final question "When is the launch, and which
product?": "Calm Barrier Cream launches on November 14th." (correct).

Before the verbatim rule, the same script re-summarized the summary each time.
The third summary lost both facts, and the final answer was "Launch Date: July
26th." In a direct test of that re-summarization step, `gemma3:1b` kept both
facts in only 3 of 5 runs, with or without a stronger instruction. Later passes
save less because the kept summary grows.

## Story 2: See context use and trust what Sensai remembers

As a creator, I want to see how much context is used and keep my history if a
summary fails, so that I can trust what Sensai remembers.

Acceptance criteria:
1. `/context` shows the budget, the last count, the number of summaries and the
   tokens saved (count before each summary minus the count on the turn after).
2. If the summary request fails (Ollama stopped), times out or is cancelled
   with Ctrl+C/Esc, a warning is printed, no message is lost and the chat
   continues.
3. Quitting and resuming with `--session <id>` restores the summary message,
   and the chat continues from it.

Tests: `test_failed_summary_keeps_full_history_and_chat_continues` (error and
Ctrl+C), `test_too_few_old_messages_does_nothing`,
`test_resumed_session_contains_summary`,
`test_missing_counts_use_character_estimate`; in `test_compression.py`
`test_failed_or_empty_summary_keeps_full_history`,
`test_ctrl_c_during_summary_keeps_full_history`,
`test_cancelled_summary_keeps_full_history`.

Measured on 2026-10-26: resuming the session above with `--session` and asking
"when is the launch and what is the hero product?" gave "November 14th. The
hero product is Calm Barrier Cream." `/context` counters (summaries, saved)
count the current run only; they start at 0 after a restart.

## Known limits

- With a small budget and long replies, the last 4 messages alone can be close
  to 80%, so summaries happen every turn or two and save less each time.
- Message numbers shown by `/history` (T34) shift after a summary.
- The tool loop (T18) is not implemented yet; tool-pair handling is tested on
  the documented block format only.
