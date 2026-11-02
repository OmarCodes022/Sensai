# File structure

This tree lists the tracked files that matter, with one line each.

## Repository root

```text
.
├── README.md               project summary, setup and usage
├── pyproject.toml          package metadata, dependencies, the sensai commands, pytest settings
├── requirements.txt        installs the project in editable mode with its test extra
├── requirements-docs.txt   MkDocs Material, to build this site
├── mkdocs.yml              site settings and navigation
├── .env.example            sample configuration to copy to .env
├── .gitignore
├── .github/workflows/      GitHub Actions workflows
├── src/sensai/             the assistant, shared by the terminal and the web page
├── web/sensai_web/         the web server; static/js/ is the page
├── data/                   the demo inputs: brand claims, DMs, engagement, docs/
├── tests/                  unit and integration tests
├── evals/                  keynote demo, answer scoring, prompt and search comparisons, adversarial
└── docs/                   this documentation
```

## Application: `src/sensai/`

One package per area; the terminal (`cli/`) and the web server call the same modules.

```text
src/sensai/
├── __main__.py            python -m sensai
├── settings.py            every SENSAI_* setting, from the environment and .env
├── engagement_demo.csv    fictional figures the MCP server reads by default
├── llm/                   Ollama over HTTP: chat stream, structured JSON, embeddings, the client factory
├── chat/                  a turn: session, personas, prompts, saved sessions, context and summaries,
│                          /think (reasoning.py), /team (agents.py), facts, ask_user, picked examples
├── tools/                 registry.py (tool loop, calculator), sandbox.py (run_python), search.py (web)
├── rag/                   basic.py (document library, search_docs), advanced.py (filter and rerank)
├── guardrails/            rules.py (patterns and claims), client.py (wraps the model)
├── campaign/              the weekly document: models, schema-forced edits, the store
├── weekly/                the weekly run: inputs, the four outputs, run
├── mcp/                   client.py (stdio client, trust, catalogue), server.py (sensai's own server)
├── security/              filesystem.py (allow and deny rules), file_tools.py (read, write, create)
├── release/               export.py, share.py (public links), schedule.py (drafts on a timer)
├── quality/               judge.py (EV1), usage_log.py (EV3), prompt_versions.py (A4), telemetry.py
├── memory/                sqlite_store.py (sessions, profiles, facts), vector_index.py, semantic_cache.py
├── core/                  messages, errors, cancellation, killable child processes, ports
└── cli/                   main.py (the sensai command and slash commands), one file per command group
```

## Tests and evaluation

```text
tests/
├── fixtures/              fictional Serein Studio data: brand, DMs, posts, engagement.csv
├── helpers/               shared test code, importable from every test
│   ├── fakes.py           FakeClient, scripted_terminal(), in-memory fake ports
│   ├── port_assertions.py reusable checks for port implementations
│   ├── tool_handlers.py   importable handlers for spawned-tool tests
│   └── sandbox_handlers.py run_python with small limits
├── unit/                  offline tests, one folder per package
│   └── conftest.py        keeps test databases in a temp folder and skips title requests
└── integration/           live tests against Ollama, skipped when it is not available

evals/adversarial/
├── README.md              how to run the manual runner
├── runner.py              sends attack turns to the model and records your verdicts
├── cases/                 written attack cases, one file per category
└── report.md              dated report of the attacks run so far
```

## Documentation: `docs/`

```text
docs/
├── README.md              home page
├── overview/              features, how it works, user stories
├── user-guide/            install, chatting, personas, sessions, tools
└── developer-guide/       architecture, files, storage, extending, testing, contributing
```

## Where to look when you want to…

- **Change the default instructions:** `src/sensai/chat/system_prompt.txt`.
- **Add or edit a built-in persona:** `src/sensai/chat/personas.json`; see
  [Extending](extending.md).
- **Change how a persona becomes instructions:** `src/sensai/chat/personas.py`.
- **Add a tool:** a definition and a handler, registered in `_tools()` in
  `src/sensai/cli/main.py`; see [Extending](extending.md).
- **Change the sandbox limits:** `SandboxLimits` in `src/sensai/tools/sandbox.py`.
- **Add an in-chat command:** `repl()` in `src/sensai/cli/main.py`.
- **Add an option or a setting:** `parse_args()` in `src/sensai/cli/main.py`,
  `src/sensai/settings.py` and `.env.example`.
- **Change what is saved after a turn:** `SessionRecorder` in
  `src/sensai/chat/saved_sessions.py`.
- **Change the database schema:** `src/sensai/memory/sqlite_store.py`; see
  [Storage](storage.md).
- **Change the request sent to Ollama:** `src/sensai/llm/ollama.py` and
  `src/sensai/llm/ollama_api.py`.
- **Change the approval prompt:** `src/sensai/cli/approval.py`.
- **Change Ctrl+C and Esc handling:** `src/sensai/cli/terminal.py` and
  `src/sensai/core/cancellation.py`.
