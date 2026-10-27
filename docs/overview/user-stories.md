# User stories

Four stories follow Nadia, solo creator of the fictional skincare brand Serein
Studio, through her week. Together they cover every feature. Test files are
under `tests/unit/`; a criterion without a test file is checked by hand with a
real command.

### Story 1: Prepare posts with the right persona

As a solo skincare creator, I want to draft captions with a writing persona, built-in or my own, and then switch to the community persona in the same chat, so that each task gets the right tone without losing what I already said.

Features: Base chat (B1), Personas (A5)

Acceptance criteria:
- `sensai --list-personas` prints `redaction: Rédaction`, `communaute: Communauté` and `analyse: Analyse` without a model or Ollama (`cli/test_personas.py`).
- `sensai gemma3:1b` uses that model even when `SENSAI_MODEL` names another one (`cli/test_main.py`).
- Without a model argument, Sensai uses the model in `SENSAI_MODEL`; with neither, it stops with `error: no model given: pass one or set SENSAI_MODEL in .env`.
- Each reply is printed chunk by chunk as the model streams it (`cli/test_personas.py`).
- `/persona communaute` prints `Persona sélectionnée : communaute`, and the next request holds the new persona and every earlier exchange (`cli/test_personas.py`).
- `/persona` with an unknown ID prints `error: unknown persona: <id>` and changes neither the persona nor the conversation (`cli/test_personas.py`).
- A JSON file given with `--personas-file` or `SENSAI_PERSONAS_FILE` replaces the built-in personas without any code change: only its entries are listed and can be selected (`cli/test_personas.py`).

### Story 2: Pick up where I left off

As a creator who works in short sessions, I want to resume my own earlier chats with my preferences already known, so that I can continue the next day without repeating myself.

Features: Sessions and profile (M1), Personas (A5)

Acceptance criteria:
- A new chat prints `Session <id>` and is saved to `sensai.sqlite3` after its first completed exchange, not before (`cli/test_sessions.py`).
- `sensai --list-sessions` prints each session's ID, last update (UTC) and title, newest first, without a model (`cli/test_sessions.py`).
- `sensai gemma3:1b --session <id>` restores the earlier exchanges and the saved persona (`cli/test_sessions.py`).
- `/history` lists my own messages, numbered from 1, one line each, without calling the model (`cli/test_history.py`).
- A profile given once with `--profile-file` is added to the instructions of every later chat (`cli/test_sessions.py`).
- Sessions and profiles saved with `--creator alice` stay apart from those of `--creator bob`: neither creator sees or resumes the other's (`cli/test_sessions.py`).

### Story 3: Check my numbers with Python instead of guessing

As a creator who reports on her weekly reach, I want to compute my figures with Python on my exported data, so that my report holds real numbers, not invented ones.

Features: Tools, Python sandbox

Acceptance criteria:
- `/tools` lists `calculate` and `run_python` without calling the model (`cli/test_sandbox_cli.py`).
- When the model calls a tool, Sensai prints one `Using tool: …` line, never the raw request, and the model continues with the result (`cli/test_tool_display.py`).
- With `SENSAI_DATA_DIR=tests/fixtures`, a `run_python` call first shows `Run run_python?` and the code; after `y`, the code reads `engagement.csv` and the model receives its output (`cli/test_sandbox_cli.py`).
- `/run <file.py>` runs a local script in the sandbox and prints `Exit code …` and its output, without the model and without changing the chat history (`cli/test_sandbox_cli.py`).
- The code sees none of Sensai's settings or API keys, and its temporary folder is gone after the run (`test_sandbox.py`).

### Story 4: Stay in control when something goes wrong

As a creator who is not a developer, I want to understand every error and stop anything at any time, so that a failure never breaks my chat or runs code I did not approve.

Features: Base chat (B1), Sessions and profile (M1), Tools, Python sandbox

Acceptance criteria:
- With Ollama stopped, a message prints `error: cannot reach Ollama, is it running? try: ollama serve` and the chat goes on.
- A model that is not installed gives `error: model '<name>' not found, try: ollama pull <name>`.
- An empty message prints `Please type something.` and nothing is sent to the model.
- Ctrl+C or Esc during a reply stops it and prints `Réponse interrompue`; the text already printed stays on screen (`cli/test_terminal.py`, `cli/test_personas.py`).
- A turn that runs past the `--operation-timeout` limit prints `Délai maximal dépassé`; the text already printed stays and the exchange is dropped (`cli/test_main.py`).
- An interrupted or failed exchange is neither kept in the conversation nor saved (`cli/test_sessions.py`).
- Answering `n` to `Run run_python?` runs nothing and prints `Using tool: run_python · tool approval refused` (`cli/test_sandbox_cli.py`).
- When the code fails, Sensai prints `Using tool: run_python · Exit code 1 · …` and the model receives the traceback (`cli/test_sandbox_cli.py`).
- The sandbox stops code that runs past its time limit, reports `Time limit reached (15 s)` with the default limit, and leaves no temporary folder (`test_sandbox.py`).

## Coverage

| Feature | Stories |
| --- | --- |
| Base chat (B1) | 1, 4 |
| Personas (A5) | 1, 2 |
| Sessions and profile (M1) | 2, 4 |
| Tools | 3, 4 |
| Python sandbox | 3, 4 |
