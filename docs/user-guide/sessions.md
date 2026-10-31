# Sessions and profile

Sensai saves every chat so you can continue it later, and adds your creator
profile to every chat so you don't repeat it.

## Saving

Each chat gets a short ID, printed when it starts:

```text
Session k7f2qa
```

Sensai saves the session to `sensai.sqlite3` after its first completed
exchange, then after each one. Interrupted, failed or empty exchanges are never
saved. After the first save, a short separate request asks the model for a
title; if that fails, the start of your first message becomes the title.

## Listing and resuming

```bash
.venv/bin/sensai --list-sessions                 # no model or Ollama needed
```

```text
k7f2qa  2026-10-14 15:02  Morning hydration post ideas
```

Each line shows the ID, the last update in UTC and the title, most recent
first. To resume a session:

```bash
.venv/bin/sensai gemma3:1b --session k7f2qa
```

```text
Session k7f2qa — Morning hydration post ideas
```

Resuming restores every completed exchange, tool results included, and the
persona saved with the session. `--persona` replaces that persona. An unknown
ID stops Sensai with `error: unknown session: k7f2qa (see --list-sessions)`.

## Rereading your messages

`/history` lists your own messages of the current session, numbered from 1, one
line each. Replies and tool results are left out, and the model is not
contacted.

```text
> /history
1. Suggest a title for a post about morning hydration.
2. Now write the caption in French.
```

A line is cut after 100 characters, and a message of several lines shows its
first line; both end with ` …`. A session without messages prints
`Aucun message dans cette session.`

## Editing an earlier message (branching)

`/edit N <new text>` continues the conversation from your message number N (as in
`/history`) with the new text, as a **new saved session**. Everything before message N
is kept; message N and what followed are left out. The original conversation is never
changed and can still be resumed.

```text
> /edit 2 Write the caption in English instead.
New branch m4tq8z from k7f2qa (k7f2qa is kept unchanged).
```

The branch is titled like the original plus `(branch)`. A wrong number or missing text
prints a short error and changes nothing. If the reply is interrupted (Ctrl+C or Esc) or
fails, nothing is saved and you stay in the original conversation. Ctrl+C or Esc during
any reply still stops it and drops the unfinished turn, so you can redirect right away.

In the web chat, type `/edit N <new text>`, or click the branch icon under one of your
messages to fill the box with `/edit N` and its text. When the reply completes, the page
opens the branch; the Stop button interrupts as usual.

## In the web interface

The **Sessions** page can rename, export (Markdown file) and delete a saved conversation;
the open conversation cannot be deleted. Click the model name in the top bar to switch to
another model installed in Ollama. The **Profile** page edits the profile as a list of
named lines (or as JSON). The Keynote page is hidden unless the address has `?keynote`.

## Creator profile

A profile is a JSON object whose keys and values are non-empty strings, for
example in `profil.local.json`:

```json
{"ton": "direct", "public": "créatrices beauté"}
```

```bash
.venv/bin/sensai gemma3:1b --profile-file profil.local.json
```

The file replaces the stored profile. From then on, every chat of this creator
adds the profile to the model's instructions, even without the option. An
empty object `{}` clears it. `SENSAI_PROFILE_FILE` does the same as
`--profile-file`.

A creator with no stored profile starts from `data/profile.json` (a shared sample you can
edit); it never overwrites a profile that is already stored. `data/brand.json` holds the
sample brand facts and approved claims the sandbox can read.

## Creators and database file

| Option | Variable | Default | Effect |
| --- | --- | --- | --- |
| `--creator` | `SENSAI_CREATOR` | `default` | Keeps the sessions and profiles of different creators apart |
| `--db` | `SENSAI_DB` | `sensai.sqlite3` | SQLite file, relative to the folder you start Sensai from |

## Good to know

- The database is plaintext: anyone who can read the file can read your chats.
- The creator key is a label, not a password: anyone can pass any `--creator`.
- If a save fails, Sensai prints `error: session not saved: …` and the chat
  goes on; the next save writes the whole history.
- `/persona` in a saved session also updates its saved persona.
- When you resume, `SENSAI_PERSONA` is ignored: only `--persona` replaces the
  saved persona.
- If the saved persona no longer exists, Sensai stops with
  `error: persona '<id>' saved with session <id> is no longer available; pass --persona`.
- Git ignores `sensai.sqlite3` and files ending in `.local.json`.
