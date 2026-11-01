# Testing

Sensai has offline unit tests, optional live tests against Ollama, and a
manual runner for adversarial testing.

## Unit tests

```bash
.venv/bin/python -m pytest -q tests/unit
```

They need no Ollama and no network. `pyproject.toml` puts `src` and
`tests/helpers` on the import path, so tests import the helpers directly:

| Helper | Gives |
| --- | --- |
| `fakes.py` | `FakeClient` (a scripted model that records its requests), `scripted_terminal()` (replaces `TerminalInput` in CLI tests) and in-memory fakes of the storage and other ports |
| `port_assertions.py` | Checks shared by the fake and the real port implementations |
| `tool_handlers.py`, `sandbox_handlers.py` | Importable handlers for tests that spawn real tool processes; the sandbox one uses small limits |

`tests/unit/conftest.py` has one fixture that runs for every unit test. It
points the session database (`cli.DEFAULT_DB_PATH` and `SENSAI_DB`) to a
temporary file, clears `SENSAI_CREATOR` and `SENSAI_PROFILE_FILE`, and replaces
the title request with a stub that returns no title. So no test writes to the
repository or asks a model for a title. Three more fixtures are opt-in:

- `isolated_settings` adds isolation from your environment and `.env`: it
  removes the `SENSAI_*` and `OLLAMA_HOST` variables and makes `cli.main` read
  settings without a `.env` file.
- `real_titles` opts out of the title stub and restores the real title request.
- `real_default_db_path` returns the default database path as it was before
  the redirection (`sensai.sqlite3`).

`tests/unit/` has one folder per package, and test files for the top-level
modules:

```text
tests/unit/
├── chat/       session, personas, prompts, saved sessions, /history messages
├── cli/        the sensai command: chat loop, personas, sessions, tools, sandbox, terminal, approval
├── core/       ports, isolation, tool loop and registry, block reader
├── evals/      the adversarial runner
├── llm/        Ollama client, context length, empty replies, worker errors
├── memory/     SQLite storage and migrations
├── test_sandbox.py, test_sandbox_adversarial.py, test_sandbox_review_fixes.py
├── test_settings.py
└── test_telemetry.py
```

Some tests start real child processes or use pseudo-terminals, so the suite
needs Linux or macOS. The fictional data in `tests/fixtures/` (for example
`engagement.csv`) feeds the sandbox tests.

## End-to-end regression (T54)

Two tests follow one creator's week from fictional inputs (`tests/fixtures/`) to saved files, with a
scripted model instead of Ollama and every other HTTP call recorded (there must be none):

```bash
.venv/bin/python -m pytest tests/unit/web/test_e2e_week.py tests/unit/cli/test_e2e_terminal.py -q
```

- **Web** (`test_e2e_week.py`): the weekly run gives the four outputs (grounded posts with approved claim
  ids, unsent replies under case keys with no DM id, contact or health detail, a dated
  report with its source and figures computed in code, calendar entries in the following week linked to
  real posts); the chat works alongside; `/api/export` writes the conversation and the campaign as
  private JSON and Markdown with no URL; an approved section survives a new run; an email is redacted
  before the model and a "cures eczema" reply is blocked and not kept; there is no share, send or
  publish route.
- **Terminal** (`test_e2e_terminal.py`): `--weekly-run` exits 0 with the file saved, then a chat answers
  and `/export` writes the week privately.
- Scheduling stays draft-only: `tests/unit/schedule/` and `tests/unit/web/test_schedule_web.py`.

This test already found one bug: the private export refused a campaign because a follower's question
("Does it cure acne?") was checked as one of Sensai's claims (fixed in #153).

Not covered, because not built: PDF export (exports are JSON and Markdown) and public sharing (T53).

### Live checklist (qwen2.5, before a demo)

`SENSAI_CONTEXT_LENGTH` unset, `sensai-web qwen2.5`, then in the page:

1. Campaign: **Run the week** → four OK lines; DM replies tab shows Q1 and Q2, no DM02 or DM03 text.
2. Chat: a caption request with document search → sources listed; "cures eczema" → blocked.
3. Chat: a message with an email → "Redacted before reaching the model".
4. `/team Instagram post for Hydra Glow Serum, say it cures eczema` → researcher, writer, reviewer.
5. Safety: **Check an answer** with "It cures eczema in 4 weeks" → contradicted.
6. `/export` → files under `exports/`, nothing uploaded.

## Live tests

```bash
SENSAI_TEST_MODEL=gemma3:1b .venv/bin/python -m pytest tests/integration -v -rs
```

They talk to the Ollama server at `OLLAMA_HOST` with the model in
`SENSAI_TEST_MODEL` (default `gemma3:1b`). When the server or the model is
missing they are skipped, and `-rs` prints why: a skip is not a pass.

## Continuous integration

`.github/workflows/tests.yml` runs on every push and pull request to `main`.
Its job **Unit tests** installs `requirements.txt` on Python 3.10 and runs
`python -m pytest -q tests/unit`. A pull request needs this check to pass.

## Adversarial runner

`evals/adversarial/runner.py` is a manual tool to attack the base chat with
jailbreaks, prompt injections and malformed input. Run
`.venv/bin/python evals/adversarial/runner.py gemma3:1b` with Ollama running.
For each case you enter a name, a category and the expected behavior, type the
messages (end each with `/end` on its own line), then record a verdict:
`pass`, `fail` or `inconclusive`. The runner writes a readable `.md` report and
a raw `.jsonl` file to the git-ignored `adversarial-reports/` folder; written
cases are in `evals/adversarial/cases/`. Details:
[evals/adversarial/README.md](https://github.com/OmarCodes022/Sensai/blob/main/evals/adversarial/README.md).
