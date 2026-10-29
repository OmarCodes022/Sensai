# Personas

A persona gives the assistant a role, a tone and a scope for one kind of work.
You can switch persona in the middle of a chat; the new one sees the whole
conversation.

## Built-in personas

| ID | Name | What it does |
| --- | --- | --- |
| `redaction` | Rédaction | Drafts Instagram posts and captions in the brand voice you supply, two variants by default |
| `communaute` | Communauté | Prepares unsent replies to comments and DMs, from fictional or anonymized questions |
| `analyse` | Analyse | Interprets the aggregate Instagram figures you supply and prepares a weekly report with recommendations |

Without a persona, the model gets the shared rules, your creator profile if
you have one, and the list of tools.

## Choose and switch

```bash
.venv/bin/sensai --list-personas                  # no model or Ollama needed
.venv/bin/sensai gemma3:1b --persona redaction    # start with a persona
```

`SENSAI_PERSONA` also sets the starting persona; `--persona` wins over it.

In a chat:

```text
> /persona
redaction: Rédaction
communaute: Communauté
analyse: Analyse

> /persona analyse
Persona sélectionnée : analyse
```

The switch applies from your next message. Earlier exchanges stay in the
conversation, so you can ask the new persona about them.

## Your own personas

`data/personas.json` (shared with the team through git) is used when it exists, otherwise
the built-in list. The web **Personas** page adds, edits and removes personas and saves them
to that file; the web chat starts on the first persona. Another JSON file can replace the list:

```bash
.venv/bin/sensai gemma3:1b --personas-file personas.local.json --persona editor
```

The file holds a non-empty array. Each entry has exactly these five fields,
all non-empty strings, and each `id` is unique:

```json
[{"id": "editor", "name": "Édition", "tone": "Warm and concise.",
  "role": "Review supplied caption drafts.",
  "response_scope": "Suggest two revisions using only supplied approved claims."}]
```

`SENSAI_PERSONAS_FILE` does the same as `--personas-file`. Git ignores files
ending in `.local.json`.

## Good to know

- An invalid file stops Sensai before it contacts the model, for example
  `error: cannot load personas: persona 1 must contain exactly: id, name, response_scope, role, tone`.
- An unknown ID at startup stops Sensai with `error: unknown persona: <id>`. In
  a chat, `/persona <id>` prints the same error and changes nothing.
- The persona instructions are in French. They tell the model to answer in the
  language you ask for, or else in the language of your latest message.
- The terminal's `/persona` switches only between the personas loaded at startup. Edit
  them in the web page, or edit the file and restart Sensai.
- A persona is a set of instructions for the model. Small models do not always
  follow them, so check drafts and figures before you use them.
- A saved session remembers its persona: see
  [Sessions and profile](sessions.md).
