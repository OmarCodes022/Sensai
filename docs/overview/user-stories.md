# User stories

Eight stories follow Nadia, solo creator of the fictional skincare brand Serein
Studio, through her week. Together they cover every feature.

### Story 1: Prepare posts with the right persona

As a solo skincare creator, I want to draft captions with a writing persona, built-in or my own, and then switch to the community persona in the same chat, so that each task gets the right tone without losing what I already said.

Acceptance criteria:
- `sensai --list-personas` prints `redaction: Rédaction`, `communaute: Communauté` and `analyse: Analyse` without a model or Ollama.
- `sensai gemma3:1b` uses that model even when `SENSAI_MODEL` names another one.
- Without a model argument, Sensai uses the model in `SENSAI_MODEL`; with neither, it stops with `error: no model given: pass one or set SENSAI_MODEL in .env`.
- Each reply is printed chunk by chunk as the model streams it.
- `/persona communaute` prints `Persona sélectionnée : communaute`, and the next request holds the new persona and every earlier exchange.
- `/persona` with an unknown ID prints `error: unknown persona: <id>` and changes neither the persona nor the conversation.
- A JSON file given with `--personas-file` or `SENSAI_PERSONAS_FILE` replaces the built-in personas without any code change: only its entries are listed and can be selected.

### Story 2: Pick up where I left off

As a creator who works in short sessions, I want to resume my own earlier chats with my preferences already known, so that I can continue the next day without repeating myself.

Acceptance criteria:
- A new chat prints `Session <id>` and is saved to `outputs/sensai.sqlite3` after its first completed exchange, not before.
- `sensai --list-sessions` prints each session's ID, last update (UTC) and title, newest first, without a model.
- `sensai gemma3:1b --session <id>` restores the earlier exchanges and the saved persona.
- `/history` lists my own messages, numbered from 1, one line each, without calling the model.
- A profile given once with `--profile-file` is added to the instructions of every later chat.
- Sessions and profiles saved with `--creator alice` stay apart from those of `--creator bob`: neither creator sees or resumes the other's.

### Story 3: Check my numbers with Python instead of guessing

As a creator who reports on her weekly reach, I want to compute my figures with Python on my exported data, so that my report holds real numbers, not invented ones.

Acceptance criteria:
- `/tools` lists `calculate` and `run_python` without calling the model.
- When the model calls a tool, Sensai prints one `Using tool: …` line, never the raw request, and the model continues with the result.
- With `SENSAI_DATA_DIR=tests/fixtures`, a `run_python` call first shows `Run run_python?` and the code; after `y`, the code reads `engagement.csv` and the model receives its output.
- `/run <file.py>` runs a local script in the sandbox and prints `Exit code …` and its output, without the model and without changing the chat history.
- The code sees none of Sensai's settings or API keys, and its temporary folder is gone after the run.

### Story 4: Stay in control when something goes wrong

As a creator who is not a developer, I want to understand every error and stop anything at any time, so that a failure never breaks my chat or runs code I did not approve.

Acceptance criteria:
- With Ollama stopped, a message prints `error: cannot reach Ollama, is it running? try: ollama serve` and the chat goes on.
- A model that is not installed gives `error: model '<name>' not found, try: ollama pull <name>`.
- An empty message prints `Please type something.` and nothing is sent to the model.
- Ctrl+C or Esc during a reply stops it and prints `Réponse interrompue`; the text already printed stays on screen.
- A turn that runs past the `--operation-timeout` limit prints `Délai maximal dépassé`; the text already printed stays and the exchange is dropped.
- An interrupted or failed exchange is neither kept in the conversation nor saved.
- Answering `n` to `Run run_python?` runs nothing and prints `Using tool: run_python · Run 1 · tool approval refused`.
- When the code fails, Sensai prints `Using tool: run_python · Run 1 · Exit code 1 · …` and the model receives the traceback.
- The sandbox stops code that runs past its time limit, reports `Time limit reached (15 s)` with the default limit, and leaves no temporary folder.

### Story 5: Get real numbers even when the first try fails

As a skincare creator, I want Sensai to compute my engagement figures with code and fix its own mistakes, so that my weekly report uses real numbers without me debugging Python.

Acceptance criteria:
- When the code fails, Sensai prints `Using tool: run_python · Run 1 · Exit code 1 · …` and the last error line, such as `KeyError: 'engaged'`; the model receives the traceback, and its fixed code runs as `Run 2`.
- The model receives the exit code and only the last 2,000 characters of the output and of the errors, with the line `If it failed, fix the code and call run_python again; otherwise answer using this output.`.
- With `SENSAI_DATA_DIR=tests/fixtures`, asking for the average engagement rate from 21 to 27 Sep "computed with Python" gives an answer that quotes `11.7`, the number the code printed.
- After 3 runs in one question, a 4th call runs nothing and prints `Using tool: run_python · Stopped after 3 attempts`; the model answers with the last error and the chat goes on.
- The model knows the names of the data files, never their contents, and still knows them after `/persona` and `--session`.

### Story 6: Approve every run and choose what the code sees

As a creator, I want to approve code before it runs and control which files it sees, so that nothing runs on my computer without my say.

Acceptance criteria:
- Sensai asks before each run, fixes included; `n` runs nothing and prints `Using tool: run_python · Run 1 · tool approval refused`.
- A question that needs no computation runs no code and asks nothing.
- Each data file is checked before it is copied: a file that is not allowed, or whose check fails, is not copied, and the model reads `Not available (not allowed): <names>`. Until file permissions exist, every file is allowed.
- Ctrl+C during a run or a fix stops the loop, prints `Réponse interrompue` and leaves no process or temporary folder.
- The code, its results and the answer are saved with the session and come back with `--session <id>`.

### Story 7: See how Sensai reached its answer

As a skincare creator, I want to see how Sensai planned, which tools it used and how it checked a post, so that I can trust its figures and know it didn't slip in a claim I'm not allowed to make.

Acceptance criteria:
- `/think <request>` shows `Plan`, then each tool call under `Act` with its result under `Observe`, then `Draft`, `Check — ok` and `Final answer (<r> rounds, <t> tool calls)` with the answer, in that order.
- A request that needs no tool shows `Plan`, `Draft`, the check and the final answer, with no `Act`.
- The check receives the request, the plan, every tool result and the draft; a draft whose number differs from a tool result is flagged.
- A draft with an unapproved claim is listed under `Check — 1 problem`, and the `Revise` step gets the problem back and replaces the draft.
- A tool error is shown under `Observe` and the loop goes on.
- Tool calls and results are shown with control characters escaped, and `run_python` still asks before it runs; a refusal is shown as the observation.
- Only my request and the final answer join the conversation and the saved session; a follow-up such as `make it shorter` works from the final answer.

### Story 8: Never wait forever for a flawed answer

As a creator, I want Sensai to stop after a fixed number of steps and tell me what is still wrong, so that I never wait forever or get a flawed answer presented as final.

Acceptance criteria:
- One `/think` makes at most 8 model replies and 3 checks; with fewer than 2 replies left, the model answers without tools.
- When the budget runs out, the remaining problems are listed under `Unresolved` and the last draft is the answer.
- A check reply that is not valid JSON shows `Check unavailable`, never `Check — ok`.
- Ctrl+C or Esc during the plan, a tool call or the check prints `Réponse interrompue`; a step past its deadline prints `Délai maximal dépassé`; nothing is added or saved, and the next message works.
- `/think` alone prints `usage: /think <request>`, and messages without `/think` behave as before.

## Coverage

| Feature | Stories |
| --- | --- |
| Base chat (B1) | 1, 4, 8 |
| Personas (A5) | 1, 2 |
| Sessions and profile (M1) | 2, 4, 6 |
| Tools | 3, 4, 7 |
| Python sandbox | 3, 4, 5, 6 |
| Self-correcting code (T2) | 5, 6 |
| Reasoning step by step (A1) | 7, 8 |
