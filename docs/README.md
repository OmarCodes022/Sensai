# Sensai

Sensai is a command-line AI assistant for a creator who runs her own skincare
brand. It chats with a local model through [Ollama](https://ollama.com), streams
its replies, switches between working personas and remembers past sessions. It
can also compute figures with a calculator or a short Python program instead of
guessing them.

## Who it is for

Nadia runs the fictional skincare brand Serein Studio on her own. Each week she
drafts Instagram captions, prepares answers to her community's questions and
reviews last week's numbers. She opens Sensai in her terminal, drafts captions
with the writing persona, switches to the analysis persona for her report, and
lets Sensai run Python on her exported engagement figures. The next day she
resumes the same session where she left off.

## Features

| Feature | What it does | Guide |
| --- | --- | --- |
| Base chat (B1) | Streams replies from a local model and keeps the conversation as context | [Chatting](user-guide/chatting.md) |
| Personas (A5) | Three built-in working roles, or your own from a JSON file, switchable mid-chat | [Personas](user-guide/personas.md) |
| Sessions and profile (M1) | Saves every chat, resumes it later and adds your profile to every chat | [Sessions and profile](user-guide/sessions.md) |
| Tools | Lets the model call a calculator and answer with the result | [Tools and sandbox](user-guide/tools.md) |
| Python sandbox | Runs the model's Python code on your data files, after you approve it | [Tools and sandbox](user-guide/tools.md) |

## Quick start

On Linux or macOS, with Python 3.10 or newer and Ollama running
(`ollama serve`), from the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
ollama pull gemma3:1b
.venv/bin/sensai gemma3:1b
```

Details: [Install and configure](user-guide/install.md).

## Where to go next

- [Overview](overview/features.md): what Sensai does and how it works, without code.
- [User guide](user-guide/install.md): how to install Sensai and use each feature.
- [Developer guide](developer-guide/architecture.md): how Sensai is built, tested and extended.
