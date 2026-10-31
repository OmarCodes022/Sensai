# Install and configure

This page gets Sensai running on your computer with a local model.

## Requirements

- Linux or macOS. Sensai reads the terminal through `termios`, which native
  Windows Python does not provide.
- Python 3.10 or newer.
- [Ollama](https://ollama.com) running (`ollama serve`) with at least one model
  installed (`ollama list`), for example `gemma3:1b`.

## Install

From the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env   # optional; skip if you already have a .env
```

`requirements.txt` installs Sensai in editable mode with its test tools. It
adds the `sensai` command to `.venv/bin/`; `.venv/bin/python -m sensai` does
the same thing.

## Configure

Sensai reads its settings from environment variables and from a `.env` file in
the folder you start it from. Real environment variables win over `.env`, and
command-line options win over both. Only the model is required.

| Variable | Default | Meaning | Option |
| --- | --- | --- | --- |
| `SENSAI_MODEL` | none | Model to chat with | `model` argument |
| `OLLAMA_HOST` | `http://localhost:11434` | Address of the Ollama server | `--host` |
| `SENSAI_PROMPT` | packaged prompt | Text file with the shared instructions; empty means the packaged prompt | `--prompt` |
| `SENSAI_PERSONA` | none | Persona to start with | `--persona` |
| `SENSAI_PERSONAS_FILE` | built-in personas | JSON file that replaces the built-in personas | `--personas-file` |
| `SENSAI_DB` | `sensai.sqlite3` | SQLite file for sessions and profiles | `--db` |
| `SENSAI_CREATOR` | `default` | Creator key that keeps sessions and profiles apart | `--creator` |
| `SENSAI_PROFILE_FILE` | none | JSON profile to store and add to every chat | `--profile-file` |
| `SENSAI_DATA_DIR` | none | Folder whose files are copied into each Python sandbox run | none |
| `SENSAI_TIMEOUT` | `60` | Network timeout, in seconds, for each request to Ollama | none |
| `SENSAI_OPERATION_TIMEOUT` | `120` | Maximum seconds for one complete turn | `--operation-timeout` |
| `SENSAI_CONTEXT_LENGTH` | Ollama's choice, doubled at 4096 or less | Context size in tokens; larger values use more memory | none |

For a local model, this is enough:

```dotenv
OLLAMA_HOST=http://localhost:11434
SENSAI_MODEL=gemma3:1b
```

## First chat

```bash
.venv/bin/sensai gemma3:1b
```

Type a message and the reply streams below it; type `exit` to leave.
[Chatting](chatting.md) shows what you see and every in-chat command.

## Good to know

- `.venv/bin/sensai --help` lists every option.
- `.env` and the default `sensai.sqlite3` are looked up in the folder you
  start Sensai from.
- Without `SENSAI_CONTEXT_LENGTH`, Sensai uses the window Ollama chose for your computer (`/api/ps`). Ollama often
  chooses 4096, too small next to Sensai's own instructions (about 2,000 tokens), so Sensai doubles it to 8192.
- `.env.example` lists the variables with short comments.
- The packaged prompt is `src/sensai/chat/system_prompt.txt`; it works from any
  folder.
