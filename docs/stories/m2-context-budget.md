# M2 Token Budgeting & Semantic Compression: user stories

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
5. In the web page the same happens after a turn, shown as `Context at <pct>%,
   summarizing <n> older messages…` then `<n> older messages summarized`.

## Story 2: See context use and trust what Sensai remembers

As a creator, I want to see how much context is used and keep my history if a
summary fails, so that I can trust what Sensai remembers.

Acceptance criteria:

1. `/context` shows the window and where it came from (`set`, `ollama` or
   `default`), the last count, the number of summaries and the tokens saved
   (count before each summary minus the count on the turn after), in the
   terminal and as a card in the web page.
2. `/compact` summarizes now and shows `Compacted: about X -> Y tokens`; with
   too few older messages it says there is nothing to compact.
3. If the summary request fails (Ollama stopped), times out or is cancelled
   with Ctrl+C/Esc, a warning is printed, no message is lost and the chat
   continues.
4. Quitting and resuming with `--session <id>` restores the summary message,
   and the chat continues from it.
