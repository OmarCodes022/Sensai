# Chatting

Start Sensai with a model, type a message and read the reply as it streams.
The model sees the whole conversation, so you can refer to earlier messages.

## Start a chat

```bash
.venv/bin/sensai gemma3:1b      # the model given as an argument
.venv/bin/sensai                # the model from SENSAI_MODEL
```

The argument wins over `SENSAI_MODEL`. With neither, Sensai stops:

```text
$ .venv/bin/sensai
usage: sensai [-h] [--prompt PROMPT] [--persona PERSONA] …
sensai: error: no model given: pass one or set SENSAI_MODEL in .env
```

With a model, Sensai prints its banner and the session ID, then waits for your
first message:

```text
Chatting with gemma3:1b. Type '/persona' to list profiles or 'exit' to quit.
Session k7f2qa

> Suggest a title for a post about morning hydration.
```

The reply streams below your message, then a new `>` prompt appears.

## In-chat commands

Sensai handles these lines itself; they never reach the model. Anything else,
including an unknown `/word`, is sent to the model.

| You type | What happens |
| --- | --- |
| `/persona` | Lists the personas, one `id: name` per line |
| `/persona <id>` | Switches persona from the next message, keeping the conversation |
| `/history` | Lists your own messages of this session, one line each |
| `/tools` | Lists the tools the model can use |
| `/run <file.py>` | Runs a local Python file in the sandbox, without the model |
| `exit` or `quit` | Leaves Sensai, in any letter case |
| Ctrl+D on an empty line | Leaves Sensai |

Details: [Personas](personas.md), [Sessions and profile](sessions.md) and
[Tools and sandbox](tools.md).

## Interrupt a reply

Press Ctrl+C or Esc while a reply streams. Sensai stops at once and prints
`Réponse interrompue`. The text already printed stays on screen, but the
exchange is dropped: the model won't see it and it isn't saved.

At the `>` prompt, Ctrl+C or Esc discards what you were typing: the text stays
on screen, and a fresh `>` prompt appears below it.

## Errors

After any of these messages the chat goes on, and the failed exchange is not
kept.

| Message | Cause | What to do |
| --- | --- | --- |
| `error: cannot reach Ollama, is it running? try: ollama serve` | Ollama is not running at `OLLAMA_HOST` | Start `ollama serve` |
| `error: model 'x' not found, try: ollama pull x` | The model is not installed | Run `ollama pull x`, or pick a model from `ollama list` |
| `error: Ollama timed out` | Ollama sent nothing for `SENSAI_TIMEOUT` seconds (60) | Retry, or raise `SENSAI_TIMEOUT` |
| `Délai maximal dépassé` | The turn, tool calls included, took longer than 120 s; time spent answering an approval prompt doesn't count | Raise the limit with `--operation-timeout` or `SENSAI_OPERATION_TIMEOUT` |
| `error: Ollama stopped before finishing the answer (token limit reached)` | The context is full | Set `SENSAI_CONTEXT_LENGTH=8192` |
| `error: Ollama returned no visible answer` | The model produced no text | Retry; for thinking models, set `SENSAI_CONTEXT_LENGTH=8192` |
| `Please type something.` | The message was empty | Type a message |

Problems with the configuration stop Sensai at startup, before it contacts the
model, with a message such as `error: unknown persona: x` or
`error: cannot load profile: …`.

## Good to know

- Sensai sends the whole conversation with every message. Long chats get
  slower and can fill the model's context.
- Replies are printed as plain text: Markdown such as `**bold**` shows as typed.
- Arrow keys are ignored while you type; Backspace works.
- When input is piped instead of typed, Sensai reads one line per message.
