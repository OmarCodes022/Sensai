# Getting started

This page gets Sensai running on your machine with a local model. The
[README](https://github.com/OmarCodes022/Sensai/blob/main/README.md) is the full
reference for every option and command.

## Requirements

- Python 3.10 or newer on Linux or macOS. The CLI reads the terminal through
  `termios`, which native Windows Python does not provide.
- [Ollama](https://ollama.com) running (`ollama serve`) with at least one model
  installed (`ollama list`), for example `gemma3:1b`.

## Install

From the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env   # optional; skip if you already have a .env
```

`requirements.txt` installs Sensai in editable mode with its test extra. It
provides the `sensai` and `sensai-remote` commands in `.venv/bin/`.

## Configure

Settings come from environment variables or `.env`. Real environment variables
win over `.env`, and command-line options win over both. `.env.example` lists
every variable; for a local model the defaults are enough:

```dotenv
OLLAMA_HOST=http://localhost:11434
SENSAI_MODEL=gemma3:1b
SENSAI_SSH_HOST=
```

Never put a password or a private key in `.env`. To use Ollama on another
machine, see [Local or remote Ollama over SSH](operations/remote-ollama.md).

## Chat

```bash
.venv/bin/sensai gemma3:1b    # or set SENSAI_MODEL and run .venv/bin/sensai
```

Type `exit` or `quit` (or Ctrl+D on an empty line) to leave. Ctrl+C or Esc
interrupts the current reply. In a chat, `/persona` lists the personas,
`/tools` lists the tools and `/history` lists your messages. Every completed
exchange is saved to `./sensai.sqlite3`; `--list-sessions` and
`--session <id>` resume an earlier chat.

## Run the tests

The unit tests need no Ollama and no network:

```bash
.venv/bin/python -m pytest -q tests/unit
```

The same command runs in GitHub Actions on every push and pull request to
`main`. Live integration tests and manual adversarial testing are described in
the README's
[Tests section](https://github.com/OmarCodes022/Sensai/blob/main/README.md#tests).

## Next steps

- [Architecture overview](architecture/overview.md): how the modules fit together.
- [Personas](product/personas.md) and [SQLite storage](architecture/storage.md).
- [Contributing](contributing.md): branches, commits and pull requests.
