# Long conversations

A model reads the whole conversation on every turn, and its window has a
fixed size. When a conversation gets long, Sensai summarizes the oldest
messages so the chat keeps working and early facts (a launch date, a product)
are not lost.

## How it works

- After each reply Sensai takes the token count Ollama reported for the turn,
  or estimates it as characters / 4 when Ollama reports none.
- The window is the one you set (`--context-budget`, or
  `SENSAI_CONTEXT_LENGTH`), else the one Ollama really loaded (read from
  `/api/ps` after the first reply), else 4,096.
- When a turn reaches 80% of the window, Sensai asks the model, in one extra
  request, to summarize every message between the system prompt and the last
  4 messages. Those messages are replaced by one message starting with
  `Summary of earlier conversation:`, which is saved with the session.
- The system prompt, the persona and the last 4 messages are never touched. A
  tool call and its result are never separated. An earlier summary is kept
  word for word, and the new one is added after it.
- The summary's own answer is capped at a quarter of the window, and a very
  long transcript is cut from its oldest end before it is sent.
- If the summary fails, times out or is stopped, the full history is kept and
  a warning is shown.

## In the terminal

| You type | What happens |
| --- | --- |
| `/context` | `Window 4,096 (ollama)   Last turn 1,537 (37%)   Summaries 0   Saved about 0 tokens` |
| `/compact` | Summarizes the older messages now, whatever the count, and prints `Compacted: about X -> Y tokens.` |

`sensai qwen2.5 --context-budget 2048` sets the window. It is also sent to
Ollama as `num_ctx`, so a smaller number uses less memory.

## In the web interface

- After a long turn, two lines appear under the reply: `Context at 99%,
  summarizing 2 older messages…`, then `2 older messages summarized`.
- `/context` shows a card with a meter, the window and where it came from, the
  last count, the number of summaries and the tokens saved.
- `/compact` summarizes now and shows `Compacted: about 1,571 -> 1,399 tokens`.
  The replaced messages stay visible until you reload the page; after that the
  summary is shown first.
- The context meter in the Inspector uses the same count.

API: `GET /api/context` and `POST /api/context/compact` (409
`nothing_to_compact` when there are too few older messages).

## Good to know

- The counters (summaries, tokens saved) count the current run, and restart
  with a new or resumed chat.
- Sensai's system prompt (tools, documents, profile) is large. With a window of
  2,048 tokens it fills most of it, so summaries keep the facts but save little.
  4,096 or more works better.
- Message numbers in `/history` shift after a summary.
