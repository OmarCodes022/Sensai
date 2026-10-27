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
