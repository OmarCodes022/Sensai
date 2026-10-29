# Reasoning step by step

`/think <request>` makes Sensai work through a request in visible steps instead
of answering in one go: it plans, uses tools for the figures, drafts an answer,
checks the draft and revises it if the check finds problems. Use it when the
answer holds numbers or product claims you need to trust.

## Example

```text
> /think Summarize last week's engagement (630 of 4,200 accounts engaged) and suggest a caption for Hydra Glow Serum
Plan
1. Compute the engagement rate with the calculator
2. Use only approved claims for Hydra Glow Serum
3. Write the summary and a short, warm caption
Act
calculate({"expression":"630 / 4200 * 100"})
Observe
15.0
Draft
15% of reached accounts engaged last week. "Hydra Glow Serum cures dry skin and eczema!"
Check — 1 problem
- "cures dry skin and eczema" is not an approved claim
Revise
15% of reached accounts engaged last week. "Hydra Glow Serum keeps your skin hydrated for up to 8 hours."
Check — ok
Final answer (2 rounds, 1 tool call)
15% of reached accounts engaged last week. "Hydra Glow Serum keeps your skin hydrated for up to 8 hours."
```

## The steps

| Label | What happens |
| --- | --- |
| `Plan` | The model writes a short numbered plan and says which tools may help |
| `Act` | A tool call, with its arguments, cut like `Observe` |
| `Observe` | The tool's result or error, cut to 6 lines and 500 characters (` …` marks a cut) |
| `Draft` | The model's answer |
| `Check — ok` / `Check — N problems` | A separate request compares the draft with your request, the plan, the tool results and the rules of the system prompt, and lists problems such as an unapproved claim, an invented number or a number that differs from a tool result |
| `Revise` | The model gets the problems back, may use tools again and writes a new answer, which is checked again |
| `Unresolved` | The budget ran out while problems remained; they are listed again |
| `Check unavailable` | The check reply was not valid; the last draft is shown unchecked |
| `Final answer (…)` | The number of drafts (rounds) and tool calls, then the answer again |

Tools work as in a normal message: `run_python` still asks before it runs,
and a tool error is shown under `Observe` and goes back to the model.

## Budget

One `/think` makes at most **8 model replies** (the plan, each reply around a
tool call, each draft and revision) and **3 checks**. When fewer than 2 replies
are left, the model must answer without tools. When the budget runs out with
problems, Sensai shows them under `Unresolved` and keeps the last draft as the
answer: the check never pretends to have passed.

## Deadline

Each step (the plan, each draft or revision with its tool calls, each check)
gets its own `--operation-timeout` budget (120 s by default), so a whole
`/think` can take several times that. `Délai maximal dépassé` means one step
ran past it (a check that runs past it prints `error: Ollama at … timed out`
instead). Ctrl+C or Esc stops the whole loop at any step, including a
running tool, and prints `Réponse interrompue`. During a check, it takes effect
as soon as the check reply arrives.

## What is kept

Only your request (without `/think`) and the final answer join the
conversation and are saved, so a follow-up such as `make it shorter` works from
the final answer. The plan, tool results, drafts and checks are only shown, and
a resumed session (`--session <id>`) does not contain them. A stopped or failed
`/think` adds and saves nothing, and the next message works as usual.

`/think` alone prints `usage: /think <request>`. Messages without `/think` work
exactly as before.

## Limits

- The `run_python` approval prompt (`Run run_python?`) appears before that
  round's `Act` line, together with any text the model wrote before the call:
  the round is shown once it has run.
- Tool call limits (such as the 3 `run_python` attempts) are shared by the whole
  `/think`: a `Revise` step continues the count of the `Draft` step.
- The check is a single request whose HTTP timeout is the same per-step limit
  (`--operation-timeout`). When it runs out, Sensai prints
  `error: Ollama at … timed out` and nothing is kept.

## Good to know

- The check is the same model reviewing its own draft: it catches many slips,
  not all of them. Read the final answer before you post it.
- Small models may write a weak plan or miss a problem; a larger model such as
  `qwen2.5:7b` works better.

## In the web interface

Type `/think <request>` in the chat box. The reply shows the same steps as bold headings
(Plan, Draft, Check, Revise, Final answer) and each tool call as a normal tool card, with
the usual approval for `run_python`. Only your request and the final answer are saved, so
after a reload the steps are gone. Stop works as for any reply. The same limits apply
(8 model steps, 3 checks, one deadline per step).
