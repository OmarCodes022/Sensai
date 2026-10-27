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
