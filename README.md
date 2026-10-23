# Sensai

Sensai is a command-line AI assistant for a skincare creator who runs her own
brand. It talks to a local [Ollama](https://ollama.com) model directly over
its HTTP API (no LLM framework), streams replies, keeps the conversation
history, lets the creator switch between drafting, community and analysis
personas mid-conversation, and saves sessions and a creator profile in a local
SQLite file. Python 3.10 or newer. The longer-term product goal (four
reviewable weekly outputs) is described in
[the product scope](docs/product/scope.md); it is not built yet.

## Features

Features from the subject catalogue that are implemented in the code:

| ID | Feature | What works today | Docs |
| --- | --- | --- | --- |
| B1 | Functional CLI chatbot (base chat) | Streamed replies, in-session history, clean errors (empty input, missing model, connection failure, timeout), model chosen by argument or `.env`, Ctrl+C/Esc interrupts a reply | [Overview](docs/architecture/overview.md), [cancellation](docs/architecture/cancellation.md) |
| A5 | Persona | Built-in and JSON-file personas, chosen at startup or switched with `/persona <id>` without losing history | [Persona guide](docs/product/personas.md) |
| M1 | Session Persistence & Profiles | Sessions saved after each completed turn, listed and resumed after restart; a creator profile file injected into the system prompt | [Storage](docs/architecture/storage.md) |

User stories: see [docs/stories/](docs/stories/README.md). A5 has draft
stories; B1 and M1 still need theirs.

Foundations that exist in code but are **not** complete features and are not
used by the CLI: an Ollama embedding adapter and in-memory vector index
([retrieval foundation](docs/architecture/retrieval.md)), a JSON-schema
reply adapter ([structured output](docs/architecture/structured-output.md)),
usage/event hooks ([telemetry](docs/architecture/telemetry.md)), typed policy
records ([privacy and claims](docs/product/privacy-and-claims.md)) and a manual
adversarial-test runner ([evals/adversarial](evals/adversarial/README.md)).

## Setup

Have Ollama running (`ollama serve`) and a model installed (`ollama list`).
The CLI needs a POSIX system (macOS or Linux): its terminal input uses
`termios`, which native Windows Python does not provide.
From the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env   # optional; skip if you already have a .env
```

`requirements.txt` installs this project in editable mode with its test extra;
the dependencies themselves are listed in `pyproject.toml`. Configuration comes
from environment variables or `.env` (see [`.env.example`](.env.example));
real environment variables win over `.env`, and CLI options win over both. The
default system prompt is packaged with Sensai
([`src/sensai/chat/system_prompt.txt`](src/sensai/chat/system_prompt.txt)), so
`sensai` works from any directory; `--prompt` or `SENSAI_PROMPT` selects
another prompt file (an empty value means the packaged default). **Upgrading:**
if your `.env` still has `SENSAI_PROMPT=prompts/system.txt`, delete that line;
that file no longer exists.

## Usage

### Chat with a local model

```bash
.venv/bin/sensai gemma3:1b          # or set SENSAI_MODEL and run .venv/bin/sensai
.venv/bin/python -m sensai gemma3:1b
```

Type `exit` or `quit` (or Ctrl+D on empty input) to leave. Ctrl+C or a lone
Esc interrupts the current reply: the printed text stays on screen but the turn
is dropped from history. Each turn has a 120-second budget
(`--operation-timeout` or `SENSAI_OPERATION_TIMEOUT`). For long histories or
thinking models, set `SENSAI_CONTEXT_LENGTH=8192`. A reply that ends without
visible text, or stops at the token limit, is reported as an error and not
kept in history.

### Chat with a remote model over SSH

`sensai-remote` accepts the same options and opens an SSH tunnel when
`SENSAI_SSH_HOST` is set (with `OLLAMA_HOST=http://127.0.0.1:11435`); with it
unset it behaves like `sensai`:

```bash
.venv/bin/sensai-remote --persona redaction
```

See [the SSH setup guide](docs/operations/remote-ollama.md).

### Personas

```bash
.venv/bin/sensai --list-personas                 # no model or Ollama needed
.venv/bin/sensai gemma3:1b --persona analyse
.venv/bin/sensai gemma3:1b --personas-file personas.local.json --persona editor
```

Built-in personas: `redaction` (post and caption drafts), `communaute` (unsent
reply suggestions) and `analyse` (supplied metrics and weekly
recommendations). In a chat, `/persona` lists them and `/persona analyse`
switches before the next message, keeping all completed exchanges. A custom
JSON file replaces the built-in list; each entry needs exactly `id`, `name`,
`tone`, `role` and `response_scope`, for example:

```json
[{"id": "editor", "name": "Édition", "tone": "Warm and concise.",
  "role": "Review supplied caption drafts.",
  "response_scope": "Suggest two revisions using only supplied approved claims."}]
```

Invalid files or unknown IDs fail before the model is contacted. Personas are
model instructions, not an enforced privacy or fact-checking gate. Details and
manual checks: [persona guide](docs/product/personas.md).

### Tools

`/tools` lists available tools without calling the model. Sensai currently
includes `calculate` for arithmetic with `+`, `-`, `*`, `/` and parentheses;
for example, ask it to calculate `(14 + 6) / 100 * 100`, and `run_python`
(see [Sandbox](#sandbox)). The model chooses
whether to request a tool, and the CLI prints `Using tool: calculate(...)`
before using its result. Tool protocol JSON stays hidden.

Each question allows five tool rounds followed by a final answer. Tool
errors return to the model; cancellation or a failed question drops all its
rounds from history. Successful rounds are saved together and restored on
resume. Numeric tool calls run in child processes with a 30-second default
limit; custom timed handlers must be importable/pickleable and open their
resources in the child. Interactive tools and human approval pause the
question budget. This execution isolation is not a permission sandbox.
See [the implemented tool contract](docs/tasks/tool-loop.md) for limits and
handler registration.

#### Sandbox

`run_python` lets the model run the Python it writes. Sensai always asks
first and shows the start of the code: `y` runs it, `n` refuses (the model is
told), `v` shows all of it. Set `SENSAI_DATA_DIR` to a folder whose top-level
files are copied next to the code (at most 50 MB in total):

```text
$ SENSAI_DATA_DIR=tests/fixtures .venv/bin/sensai qwen2.5:7b
> Use Python to print the average daily accounts_reached from 21 to 27 Sep in engagement.csv
Run run_python?
  code:
    import csv
    reach = []
    for row in csv.DictReader(open("engagement.csv")):
        if row["source"] == "instagram_insights_daily":
            if "2026-09-21" <= row["date"] <= "2026-09-27":
                reach.append(int(row["accounts_reached"]))
    … (+1 more line)
[y] run · [n] refuse · [v] view all y
Using tool: run_python · Exit code 0 · 0.3 s
The average daily reach from 21 to 27 Sep was 1021.4 accounts.
> /run broken.py
Running in the sandbox (limit 15 s)…
Exit code 1 · 0.2 s
stderr:
Traceback (most recent call last):
  File "main.py", line 4, in <module>
KeyError: 'reach'
```

`/run <file.py>` runs a local script the same way, without the model or an
approval, and leaves the chat history untouched. Each run gets a fresh
temporary folder (deleted afterwards), the code as `main.py`, no keyboard
input and an almost empty environment: no `.env` values, `SENSAI_*`/`OLLAMA_*`
variables or API keys. Limits: 15 s of wall-clock time, 10 s of CPU, 512 MB of
memory, 10 MB per written file, and 10,000 characters each of stdout (the
start) and stderr (the end, so the traceback survives). Ctrl+C stops the code
at once. Small models may garble code inside JSON; a larger model such as
`qwen2.5:7b` works better.

This stops runaway or careless code, **not deliberately malicious code**. The
code still has network access and can read any file your user can read by
absolute path. The memory limit only works on Linux (macOS ignores it), and
fork bombs or processes that leave their process group are not prevented.
Stronger isolation (for example `docker run --rm --network none`) is not
implemented.

### Sessions and creator profile

```bash
.venv/bin/sensai --list-sessions                 # ID, last update (UTC), title
.venv/bin/sensai gemma3:1b --session k7f2qa      # resume a saved session
.venv/bin/sensai gemma3:1b --profile-file profil.local.json
```

Every chat is saved to `./sensai.sqlite3` (gitignored; change with `--db` or
`SENSAI_DB`) after its first completed exchange; interrupted, failed or empty
turns are never saved. A short separate model request names the session; if it
fails, the start of the first message is used. Resuming restores the exchanges
and the persona (`--persona` overrides it). The profile file is a JSON object of
strings, such as `{"ton": "direct", "public": "créatrices beauté"}`; it
replaces the stored profile, which is then added to the system prompt of every
chat. `--creator` (or `SENSAI_CREATOR`) keeps sessions and profiles of different
creators apart; it is a key, not authentication. The database is plaintext.
Storage details: [storage.md](docs/architecture/storage.md).

## Tests

Offline unit tests (no Ollama, no network; scripted fakes in
`tests/helpers/`):

```bash
.venv/bin/python -m pytest -q tests/unit
```

GitHub Actions runs the same command on every push and pull request to `main`
(`.github/workflows/tests.yml`, job **Unit tests**).

Optional live tests against a running Ollama and installed model (they skip
otherwise, and a skip is not a pass):

```bash
SENSAI_TEST_MODEL=gemma3:1b .venv/bin/python -m pytest tests/integration -v -rs
```

Manual adversarial testing: see [evals/adversarial](evals/adversarial/README.md).

## Documentation

Start at the [documentation index](docs/README.md).
