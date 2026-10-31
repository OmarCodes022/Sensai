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
├── src/sensai/             the application
├── tests/                  unit and integration tests
├── evals/adversarial/      manual adversarial testing
└── docs/                   this documentation
```

## Application: `src/sensai/`

```text
src/sensai/
├── __init__.py            package marker
├── __main__.py            entry point of python -m sensai
├── settings.py            Settings read from environment variables and .env
├── tools.py               ToolRegistry, the tool loop (run_with_tools) and the calculate tool
├── sandbox.py             run_python: Python in a limited, throw-away process
├── mcp_client.py          MCP stdio client and the tool catalogue read from mcp.json
├── mcp_server.py          our MCP server: weekly_engagement over a CSV
├── engagement_demo.csv    fictional figures the server reads by default
├── telemetry.py           usage and event hooks; the CLI uses only new_operation_id
├── chat/
│   ├── __init__.py
│   ├── session.py         ChatSession: history, streaming, rollback of incomplete turns
│   ├── personas.py        PersonaRegistry: validates a catalogue, builds persona instructions
│   ├── personas.json      the built-in personas: redaction, communaute, analyse
│   ├── prompts.py         loads the system prompt file
│   ├── system_prompt.txt  the default system prompt
│   ├── saved_sessions.py  session IDs, profile file, titles, SessionRecorder
│   ├── reasoning.py       /think: plan, act/observe, draft, check and revise loop with its budget
│   └── blocks.py          BlockReader: hides the final JSON tool block while streaming
├── cli/
│   ├── __init__.py
│   ├── main.py            the sensai command: arguments, startup checks, REPL, in-chat commands
│   ├── terminal.py        raw POSIX terminal input, Ctrl+C and Esc detection, single-key reads
│   ├── approval.py        TerminalApproval: the y/n/v prompt before run_python
│   └── remote.py          sensai-remote: the same chat through an optional SSH tunnel
├── core/
│   ├── __init__.py
│   ├── messages.py        Message: role and content
│   ├── errors.py          SensaiError, LLMError, ModelNotFoundError, LLMConnectionError
│   ├── cancellation.py    CancellationToken, OperationCancelled, OperationTimedOut
│   ├── isolation.py       ControlledLLMClient, ControlledTool: work in killable child processes
│   ├── ports.py           typed interfaces and values (personas, sessions, profiles, tools, approval)
│   └── policy.py          privacy and product-claim policy records — not used by the CLI yet
├── llm/
│   ├── __init__.py        create_client()
│   ├── client.py          LLMClient interface, close_stream()
│   ├── ollama.py          OllamaClient: streaming /api/chat client
│   ├── ollama_api.py      Ollama wire format and usage records
│   ├── embeddings.py      Ollama embedding adapter — not used by the CLI yet
│   └── structured.py      OllamaStructuredClient: JSON-schema replies, used by the /think check
└── memory/
    ├── __init__.py
    ├── sqlite_store.py    StorageRepository: SQLite sessions, profiles, facts and migrations
    └── vector_index.py    in-memory vector index — not used by the CLI yet
```

`core/ports.py` also defines file and permission ports that are not used by
the CLI yet.

## Tests and evaluation

```text
tests/
├── fixtures/              fictional Serein Studio data: brand, DMs, posts, engagement.csv
├── helpers/               shared test code, importable from every test
│   ├── fakes.py           FakeClient, scripted_terminal(), in-memory fake ports
│   ├── port_assertions.py reusable checks for port implementations
│   ├── tool_handlers.py   importable handlers for spawned-tool tests
│   └── sandbox_handlers.py run_python with small limits
├── unit/                  offline tests: one folder per package, plus the top-level modules
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
- **Change the sandbox limits:** `SandboxLimits` in `src/sensai/sandbox.py`.
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
