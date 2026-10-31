# Questions and forms

When Sensai is missing a detail it needs (which product, which tone), the model asks you with
the `ask_user` tool instead of guessing. You answer in a small form and the reply continues
with your answer.

```text
> Write an Instagram caption for our launch
Sensai needs one detail:
  Which product should the caption promote?
    1) Hydra Glow Serum   2) Calm Barrier Cream   3) Other (type it)
  Choice [1-3]: 2
Here's a caption for Calm Barrier Cream: …
```

- A question is either a **choice** (numbered options, plus *Other* to type your own) or
  **text**. The model may ask up to four at once.
- An invalid choice (`9`, `x`) is asked again. **Ctrl+C** skips the form: the model is told you
  skipped it, and the chat goes on.
- The time you spend answering does not count toward the reply's time limit.
- The questions and your answers are a normal tool round, so they stay in the saved session.
- `/tools` lists `ask_user`.

## In the web interface

A **Sensai needs a detail** card appears in the reply, with radio buttons for choices (and an
*Other* box) or a text box. **Send answers** continues the reply; **Skip** skips. While the card
is open the message box waits, as for a `run_python` approval.

## Limits

Small models do not always ask when they should, and sometimes ask when they could have
answered. Asking explicitly ("ask me which product first") helps.
