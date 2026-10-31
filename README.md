# Sensai

A local AI assistant for one skincare creator. It chats with an [Ollama](https://ollama.com)
model over its HTTP API (no LLM framework), in the terminal or in your browser.
Everything stays on your computer. Python 3.10+.

Docs: <https://omarcodes022.github.io/Sensai/> (sources in [docs/](docs/README.md)).

## What it does

| Feature | How to use it | Guide |
| --- | --- | --- |
| Streaming chat | `sensai <model>`; Ctrl+C or Esc stops a reply | [Chatting](docs/user-guide/chatting.md) |
| Personas | `--persona analyse`, `/persona` to switch mid-chat | [Personas](docs/user-guide/personas.md) |
| Saved sessions and profile | `--list-sessions`, `--session <id>`, `--profile-file` | [Sessions](docs/user-guide/sessions.md) |
| Branching and interrupt | `/edit N <new text>` continues from message N as a new session; Ctrl+C, Esc or Stop interrupts a reply | [Sessions](docs/user-guide/sessions.md#editing-an-earlier-message-branching) |
| MCP (T1 ★★★) | Configure external tools in `mcp.json`, with approval for each call in terminal and web chat | [MCP setup](docs/user-guide/mcp.md) |
| Tools | the model calls `calculate` and `run_python` (you approve each run); a failed run goes back to the model, which fixes its code, up to 3 runs per question | [Tools and sandbox](docs/user-guide/tools.md) |
| Step-by-step reasoning | `/think <request>`: a plan, tool calls, a draft, a check against your rules, revisions | [Reasoning step by step](docs/user-guide/thinking.md) |
| Scheduled drafts | recurring requests from `schedule.local.json` run on their own and save dated drafts; `python -m sensai.schedule`, or the web Schedule page | [Scheduling](docs/user-guide/scheduling.md) |
| Private export | `/export` writes the conversation and the week's campaign to `exports/` as JSON and Markdown, after the guardrails; the campaign export follows every change | [Export](docs/user-guide/export.md) |
| Web search | the model calls `web_search` for current information and cites `[1]`, `[2]` with a source list; `/search <query>` | [Web search](docs/user-guide/web-search.md) |
| Questions and forms | when a detail is missing, the model asks with `ask_user`: a numbered choice in the terminal, a form card in the web chat | [Questions](docs/user-guide/questions.md) |
| Weekly campaign document | `/campaign`: four sections, edited one schema-forced JSON edit at a time; approved sections ask before any change; web Campaign page | [Campaign](docs/user-guide/campaign.md) |
| File access within permissions | `.sensai/settings.json` allow/deny rules; the model's `read_file`, `write_file`, `create_file`; `/read`, `/save` | [File access](docs/user-guide/files.md) |
| Content and privacy guardrails | emails, phones and @handles redacted; injections and health details refused before the model; unapproved claims stopped | [Guardrails](docs/user-guide/guardrails.md) |
| Brand facts memory | the model saves, corrects and deletes facts with `save_fact` / `delete_fact`; `/facts`; web Brand facts page | [Brand facts](docs/user-guide/brand-facts.md) |
| Advanced document search | filters by product and newest sheet, the model scores each passage, weak ones are dropped; sources show the score (`SENSAI_RAG=basic` to turn off) | [Document search](docs/user-guide/documents.md#advanced-search) |
| Brand document search | `/add <file>`, `/docs`; files in `data/docs/` are indexed by themselves | [Document search](docs/user-guide/documents.md) |
| Long conversations | older messages are summarized at 80% of the window; `/context` shows the count, `/compact` summarizes now (terminal and web) | [Long conversations](docs/user-guide/context.md) |
| Web interface | `sensai-web <model>` | [below](#web-interface) |

Planned work and what is not built yet: [product scope](docs/product/scope.md).

## Quick start

Needs Ollama running (`ollama serve`) and a model (`ollama pull gemma3:1b`).
The terminal chat needs macOS or Linux.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env                  # optional
.venv/bin/sensai gemma3:1b            # terminal chat
.venv/bin/sensai-web gemma3:1b        # browser, then open http://127.0.0.1:8765/
```

After pulling new code, run `.venv/bin/python -m pip install -e .` again so new
commands (like `sensai-web`) are registered. Full install guide:
[Install and configure](docs/user-guide/install.md).

## Terminal chat

```bash
.venv/bin/sensai gemma3:1b                        # or set SENSAI_MODEL and omit the model
.venv/bin/sensai gemma3:1b --persona redaction    # start as a persona
.venv/bin/sensai --list-personas                  # no Ollama needed
.venv/bin/sensai --list-sessions
.venv/bin/sensai gemma3:1b --session k7f2qa       # resume
.venv/bin/sensai-remote                           # same, through an SSH tunnel
```

In a chat: `/persona [id]`, `/tools`, `/mcp` (status and setup; `/mcp reload` after editing), `/history`, `/edit N <text>`, `/facts`, `/campaign`, `/export`, `/search`, `/read`, `/save`, `/run <file.py>`, `/docs [text]`,
`/add`, `/remove`, `/reindex`, and `exit` to leave. Each turn has a 120 s budget.
Remote Ollama: [SSH setup](docs/operations/remote-ollama.md).

## Web interface

Streaming chat, personas, saved sessions, tool approval, the Python sandbox and
your profile, in a page served from your machine.

```bash
.venv/bin/sensai-web gemma3:1b      # http://127.0.0.1:8765/ (--port to change)
```

- Same options, database, creator and `.env` as the terminal chat.
- Listens on `127.0.0.1` only. Add `?mock=1` to the address for a demo without a model.
- Tool calls (calculator, Python) work best with a larger model such as `qwen2.5`.
- Python runs follow the terminal's loop: 3 attempts per question to fix failing
  code, each card showing `Run n of 3`. A refused run also uses one of the 3.
- Page, API and design notes: [web/web-ui.md](web/web-ui.md).

## Your data

The Python sandbox reads the files in `data/` (repository root, relative to where
you launch). The folder is a placeholder in git: its contents are never pushed.
Add CSV, TSV, JSON, text or Markdown files there, or in the web page under
**Tools, then Data files** (drop files, or add example data). `SENSAI_DATA_DIR`
points elsewhere.

The sandbox stops runaway code, not malicious code: it keeps network access and
can read files by path. Limits and details: [Tools and sandbox](docs/user-guide/tools.md).

## Brand document search

Put your product sheets, FAQ and brand voice in `data/docs/` and the model searches them
whenever it needs a fact, instead of inventing one. It is on by itself; no flag.

```bash
ollama pull nomic-embed-text          # once: the embedding model
.venv/bin/sensai qwen2.5              # data/docs/ is indexed in the background
```

- **Add documents** from anywhere: `/add <file or folder>` in the chat copies them into
  `data/docs/`. Or copy files there yourself: new, edited and removed files are noticed
  and indexed automatically. `/docs` lists them, `/docs <text>` shows what a search finds,
  `/remove <name>` removes one. The web interface has the same on its **Documents** page
  (drag and drop, list, remove, search preview), and shows the sources under each reply.
- `.md` and `.txt` files; a header (`source`, `version`, `product`, `title`) is optional.
  Older versions of a sheet are marked OUTDATED in the results.
- `data/docs/` ships with fictional Serein Studio sample sheets: replace them with yours.
  Your own files stay out of git.
- `--docs <folder>` or `SENSAI_DOCS` uses another folder; `SENSAI_DOCS=` (empty) switches
  search off. Without the embedding model, search is off and chat works normally.
- Details: [Document search](docs/user-guide/documents.md).

## Configuration

Environment variables or `.env` (see [.env.example](.env.example)). Real environment
variables win over `.env`, and command-line options win over both.

| Variable | Meaning | Default |
| --- | --- | --- |
| `SENSAI_MODEL` | model to chat with | none |
| `OLLAMA_HOST` | Ollama base URL | `http://localhost:11434` |
| `SENSAI_DB` | session database | `sensai.sqlite3` |
| `SENSAI_CREATOR` | key that separates creators' sessions and profiles | `default` |
| `SENSAI_DATA_DIR` | files the sandbox can read | `./data` if it exists |
| `SENSAI_SEARCH_PROVIDER`, `SENSAI_SEARCH_API_KEY` | web search provider (`brave`, `duckduckgo`, `off`) and the Brave Search API key | Brave with a key, else DuckDuckGo |
| `SENSAI_GUARDRAILS_FILE`, `SENSAI_BRAND_FILE` | extra guardrail rules (JSON) and the brand file with the approved claims | none, `./data/brand.json` if it exists |
| `SENSAI_DOCS`, `SENSAI_EMBED_MODEL` | document folder (empty switches search off) and embedding model | `./data/docs`, `nomic-embed-text` |
| `SENSAI_OPERATION_TIMEOUT` | seconds per turn | `120` |
| `SENSAI_CONTEXT_LENGTH` | context window in tokens, also where summaries start (80%); `--context-budget` in the terminal | Ollama's choice for your computer, doubled when it is 4096 or less |
| `SENSAI_SSH_HOST` | SSH alias for a remote Ollama | none |

If your `.env` still has `SENSAI_PROMPT=prompts/system.txt`, delete that line: the file no longer exists.

## Tests

```bash
.venv/bin/python -m pytest -q tests/unit        # offline, no Ollama needed
SENSAI_TEST_MODEL=gemma3:1b .venv/bin/python -m pytest tests/integration -v -rs   # live, optional
```

CI runs the unit tests on every push and pull request. Adversarial testing:
[evals/adversarial](evals/adversarial/README.md). More: [Testing](docs/developer-guide/testing.md).

## More documentation

- [Overview](docs/overview/features.md): features, how a turn works, user stories.
- [User guide](docs/user-guide/install.md): install, chat, personas, sessions, tools.
- [Developer guide](docs/developer-guide/architecture.md): architecture, file structure, storage, adding a tool, contributing.
- [Privacy and product claims](docs/product/privacy-and-claims.md) and [product scope](docs/product/scope.md).
- Preview the docs site: `.venv/bin/pip install -r requirements-docs.txt && .venv/bin/mkdocs serve`.
