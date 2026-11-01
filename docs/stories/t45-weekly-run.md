# Weekly run: user stories

- Catalogue: integrates T2, T3, T4, T5, M4 and A1 (one run, not a new feature score)
- Drafting lead: Omar
- Status: done

Code: [`weekly/`](https://github.com/OmarCodes022/Sensai/tree/main/src/sensai/weekly/) (inputs, outputs, run),
[`cli/weekly.py`](https://github.com/OmarCodes022/Sensai/blob/main/src/sensai/cli/weekly.py) and [`weekly.py`](https://github.com/OmarCodes022/Sensai/blob/main/web/sensai_web/weekly.py) (web).
Guide: [The weekly run](../user-guide/campaign.md#the-weekly-run).

## Story 1: Prepare the whole week in one go

As Nadia, the creator of Serein Studio, I want one command to turn my brand file, my DMs and
last week's figures into the week's posts, reply suggestions, report and calendar, so that my
Monday starts with drafts to review instead of a blank page.

Acceptance criteria:
1. `sensai qwen2.5 --weekly-run data` (or **Run the week** on the Campaign page) prints one line
   per output, OK or failed, and saves the week's campaign document once, at the end.
2. The report's figures equal the weekly row of `engagement.csv` (4,200 reached, 630 engaged,
   15.0%); with zero reach the rate is `n/a (zero reach)`.
3. At least 3 posts, each quoting an approved claim word for word or promising nothing, and at
   least 3 calendar entries in the following week, each linked to one of those posts.
4. A missing file, a model failure or too few usable items fails only its own output.

Tests: `tests/unit/weekly/test_weekly.py`, `tests/unit/cli/test_weekly_cli.py`,
`tests/unit/web/test_weekly_web.py`.

## Story 2: Trust that nothing unsafe or private gets through

As Nadia, I want DMs with personal or health details left out, and every generated text
checked against my approved claims, so that I never review, let alone post, something I
could not say.

Acceptance criteria:
1. DMs marked not eligible or not privacy safe are left out with their reason; their text never
   reaches the model or the saved file, and replies use case keys (`Q1`), never DM ids.
2. A question like "Does it cure acne?" gets a suggestion that makes no cure claim.
3. A text the guardrails refuse gets one rewrite, told why, then is left out with the reason.
4. Approved sections are never changed, Ctrl+C or **Stop** saves nothing, and nothing is ever
   sent or published.

Measured on 2026-11-01 with `qwen2.5` on `tests/fixtures` and in the page: all four outputs
OK; DM02 (email) and DM03 (pregnancy) left out with their reasons and absent from the file;
DM04 answered "...They are not medicines... it's always best to consult a dermatologist."
