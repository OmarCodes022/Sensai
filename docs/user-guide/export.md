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

## Public links

One section of the week (posts, report or calendar) can be shared as a read-only page that anyone on
the same network opens without logging in, for example a teammate's phone:

```text
$ python -m sensai.share          # in another terminal: serves shares/ on port 8766
> /share calendar
Sensai wants to:
  Action:  publish a public, no-login page
  Where:   http://192.168.0.14:8766/s/thksFZFcZx61iIavBj_9rQ
  Content: Serein Studio · week 2026-W40 (2026-09-28 to 2026-10-04) · calendar
           2026-09-28 12:00 · Instagram · P1 ...
Apply this change? [y/N] y
Shared: http://192.168.0.14:8766/s/thksFZFcZx61iIavBj_9rQ   (remove with /unshare thksFZFcZx61iIavBj_9rQ)
```

- Nothing is written before your `y`: you see the exact text and the link first. The text goes
  through the guardrails; a refused claim shares nothing.
- **DM replies are never shared**: they come from customer messages. Only the chosen section
  appears, never the conversation, sources or other sections.
- The page is a snapshot: later edits do not change it. Share again for a new version.
- The link is an unguessable token. The server answers only `/s/<token>`; everything else is 404.
  `/unshare <token>` (or **Remove** on the Campaign page) deletes the page and the link answers 404.
- The link uses this computer's home network address (192.168.x first, not a VPN tunnel);
  `SENSAI_SHARE_HOST` sets it, `SENSAI_SHARE_PORT` the port, `SENSAI_SHARES_DIR` the folder (`shares/`,
  git-ignored).
- In the web page, **Share** on the posts, report or calendar tab shows the same confirm card.
- Limit: local network only; putting a link on the internet (a tunnel or hosting) is not built.

## Limits

No PDF: print the Markdown file from a viewer if you need one. A public link to share an
output is a separate feature that is not built.
