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

## In the web interface

The **Campaign** page (or `/campaign` in the chat) shows the week, its file and the four
sections as tabs, each with its status and an **Approve section** button. Below, pick posts or
calendar, write what to change and press **Ask Sensai**. For an approved section a card shows
the action, the file and the before and after, with **Apply** and **Refuse**.

## Limits

Small models sometimes leave out a field or use a claim it should not: the checks refuse the
edit, and you can ask again. `SENSAI_CAMPAIGNS_DIR` changes the folder; the documents are yours
and stay out of git.
