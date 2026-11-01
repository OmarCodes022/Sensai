# Campaign document

Each week's deliverable is one **campaign document**, not a chat transcript: four sections
(post drafts, DM reply suggestions, the weekly report and the content calendar), saved as
`campaigns/<week>.json` (for example `2026-W45`, the coming week). It grows one small,
checked edit at a time.

```text
> /campaign posts write a post about Hydra Glow Serum
Posts: add post P1
Saved campaigns/2026-W45.json
> /campaign calendar schedule P1 on Wednesday at 18:00
Calendar: add entry E1
> /campaign
Week 2026-W45 (2026-11-02 to 2026-11-08, Europe/Paris)
Posts (1)......... draft
DM replies (0).... draft
Report............ draft: no data yet
Calendar (1)...... draft
```

## How an edit works (structured output)

`/campaign posts|calendar <request>` asks the model for **one edit as JSON**, and Ollama is
forced to answer in the section's schema (`op` add, replace or remove, the item's id and its
fields). Sensai then checks it: the id exists, a calendar entry's post exists and its date is
inside the week, the time is `HH:MM`, and every claim id is approved and in date in the brand
file. Only then is the one item changed and the file saved (written to a temporary file, then
renamed, so a crash never leaves a broken file). Anything wrong is refused with a clear
message and the file is unchanged.

The report and the DM replies are filled only by the weekly run, never by a chat edit, and
report figures are always computed by code, never written by the model.

## Approving, and confirming changes (human in the loop)

`/campaign approve <section>` marks a section approved. A later edit to it is checked as
usual, then Sensai stops and shows exactly what would change:

```text
Posts are approved. Sensai wants to:
  Action:  replace post P1
  Where:   campaigns/2026-W45.json
  Before:  'Hydra Glow Serum hydrates skin for up to 8 hours.'
  After:   'Thirsty skin? Hydra Glow Serum hydrates for up to 8 hours.'
Apply this change? [y/N]
```

Only `y` applies it (the section stays approved). `n`, Enter, Ctrl+C or the end of input
change nothing. Draft sections never ask, and invalid edits are refused before any question.
The same approval object asks before a `run_python` call.

## The weekly run

One command prepares the whole week from a folder with `brand.json`, `dms.json`,
`engagement.csv` and `posts.json` (the sample files in `data/` and `tests/fixtures/`):

```text
$ sensai qwen2.5 --weekly-run data
Report ....... OK     reached 4,200 · engaged 630 · rate 15.0% (instagram_insights_weekly_unique)
DM replies ... OK     2 suggestions · 2 DMs left out (contains name and personal contact details, contains medical informations)
Posts ........ OK     4 drafts (claims C01, C03)
Calendar ..... OK     4 entries, 2026-09-28 to 2026-10-01
Report week 2026-09-21 to 2026-09-27 · calendar for 2026-09-28 to 2026-10-04
Saved campaigns/2026-W40.json: nothing was sent or published.
```

- **Report:** the figures come from the weekly row of `engagement.csv` (a date like
  `2026-09-21/2026-09-27`), computed in code; the model only writes the interpretation. Zero
  reach gives `n/a (zero reach)`; more engaged than reached fails the report.
- **DM replies:** DMs marked not eligible or not privacy safe are left out with their reason and
  never read further. The others go through the guardrails' input check, then get one reply
  suggestion each, under a case key (`Q1`, `Q2`…), never the DM's id.
- **Posts:** at least 3 captions, each quoting an approved claim word for word or promising
  nothing; checked by the guardrails and the same rules as an edit.
- **Calendar:** at least 3 entries in the following week, each linked to one of those posts.
- A refused text gets one rewrite, told why, then is left out. A missing or broken file, a model
  failure or too few usable items fails only that output. Approved sections stay as they are.
- The document is written once, at the end: Ctrl+C (or **Stop**) saves nothing. There is no
  send, publish or share step. The exit code is 0 when every output is OK.

In the page, **Run the week** on the Campaign page runs the same thing on the data folder and
shows one line per output as it finishes.

## In the web interface

The **Campaign** page (or `/campaign` in the chat) shows the week, its file and the four
sections as tabs, each with its status and an **Approve section** button. Below, pick posts or
calendar, write what to change and press **Ask Sensai**. For an approved section a card shows
the action, the file and the before and after, with **Apply** and **Refuse**.

## Limits

Small models sometimes leave out a field or use a claim it should not: the checks refuse the
edit, and you can ask again. `SENSAI_CAMPAIGNS_DIR` changes the folder; the documents are yours
and stay out of git.
