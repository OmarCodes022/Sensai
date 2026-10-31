# Private export

`/export` saves the current conversation and the week's campaign document as JSON and
Markdown in a local `exports/` folder, to read, print or paste into your notes. Nothing is
uploaded or shared.

```text
> /export
Conversation: exports/sessions/a1b2c3.json, exports/sessions/a1b2c3.md
Exported campaign: exports/campaigns/2026-W45.json, exports/campaigns/2026-W45.md
```

- **Conversation:** your messages and Sensai's replies (no system prompt, no tool protocol), as
  JSON (`role`, `content`) and as Markdown (one heading per turn).
- **Campaign:** a JSON copy and a Markdown page with the four sections and their status, the
  calendar as a table and the report figures with their source.
- **Automatic:** the campaign export is refreshed after every saved `/campaign` change and
  every approval, with one line saying so. Private export never asks for confirmation.
- **Checked first:** every text goes through the [guardrails](guardrails.md)' reply check.
  Identifiers become `[redacted]` in the exported copy; a file containing a claim that is not
  approved is not written, the reason is shown, and the previous export stays as it was.
- **Safe:** files are written to a temporary file and renamed, so a failed export never leaves
  a half-written file. Write errors (permission denied, full disk) are reported and the chat
  goes on. `exports/` is in `.gitignore`; `SENSAI_EXPORTS_DIR` changes the folder.

## In the web interface

`/export` in the chat shows a card with the files written (or why one was not). The Campaign
page has an **Export** button, and each saved edit shows where the campaign was exported.
The Sessions page can also download one conversation as Markdown.

## Limits

No PDF: print the Markdown file from a viewer if you need one. A public link to share an
output is a separate feature that is not built.
