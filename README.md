# Sensai

A Python 3.10+ assistant foundation using local Ollama through direct HTTP.
The current CLI streams replies and keeps conversation history. Storage,
embeddings, structured output, vector indexing and telemetry are separate
capabilities; the CLI does not automatically connect them into a product flow.
The intended creator workflow is described in
[the product scope](docs/product/creator-product.md).

## Setup and run

Have Ollama running locally. Use `ollama list` to choose an installed model;
start `ollama serve` in another terminal if the server is not already running.

From the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/sensai gemma3:1b
```

Replace `gemma3:1b` with your installed model. Type `exit` to quit.
Configuration comes from environment variables or a local `.env`; see
[`.env.example`](.env.example) for the available settings. Copy that example
only if you do not already have a `.env`. The default system prompt is
[`prompts/system.txt`](prompts/system.txt).

Runtime and development dependencies are defined in `pyproject.toml`.
`requirements.txt` installs the editable project with its `dev` extra; it does
not maintain another copy of the dependency list.

## Repository layout

```text
src/sensai/
  app/             CLI, settings, prompt loading and chat sessions
  core/            Messages, errors, typed contracts and policy definitions
  llm/             Ollama HTTP clients, embeddings and structured responses
  memory/          SQLite storage and local vector indexing
  observability/   Optional telemetry
scripts/
  delivery/        GitHub/Notion evidence automation
  testing/         Manual adversarial-test runner
  docs/            Local diagram-generation tooling
tests/
  helpers/         Deterministic test doubles
  unit/            Tests grouped by the responsibility they exercise
  integration/     Tests requiring real Ollama
docs/              Architecture, product, operations and testing guides
prompts/           Editable model instructions
infra/             AWS mirror infrastructure
```

Local course PDFs stay in `subject/` when provided. Local diagrams belong in
`docs/diagrams/`; the builder writes there, not beside its Python script.
Generated manual-test reports stay in gitignored `adversarial-reports/`.
Environment files, reports and course PDFs are not test fixtures.

## Tests

Run the deterministic suite without Ollama:

```bash
.venv/bin/python -m pytest tests/unit -q
```

Run the existing live B1 checks with a running server and installed model:

```bash
SENSAI_TEST_MODEL=gemma3:1b \
  .venv/bin/python -m pytest tests/integration -v -rs
```

Skipped live tests are not passing model evaluations. Diana's manual runner
accepts her own inputs, expected behavior and human verdicts:

```bash
.venv/bin/python scripts/testing/adversarial_test.py gemma3:1b
```

See [the testing guide](docs/testing/adversarial-testing.md). The runner and
its unit tests do not establish EV4 completion or resistance to all attacks.
Prompt instructions are not an enforced privacy or output-validation gate.

## Documentation and module moves

[Browse the guides](docs/README.md) for architecture, product boundaries and
delivery operations. GitHub workflows retain their existing jobs and
activation rules; only script locations changed.

Update feature branches to the new imports rather than adding compatibility
wrappers:

| Previous module | Current module |
| --- | --- |
| `sensai.cli` | `sensai.app.cli` |
| `sensai.settings` | `sensai.app.settings` |
| `sensai.prompts` | `sensai.app.prompts` |
| `sensai.session` | `sensai.app.session` |
| `sensai.contracts` | `sensai.core.contracts` |
| `sensai.errors` | `sensai.core.errors` |
| `sensai.messages` | `sensai.core.messages` |
| `sensai.policy` | `sensai.core.policy` |
| `sensai.storage` | `sensai.memory.storage` |
| `sensai.vector_index` | `sensai.memory.vector_index` |
| `sensai.telemetry` | `sensai.observability.telemetry` |

`sensai.llm` paths are unchanged. The `sensai` console command and
`python -m sensai` still start the CLI.
