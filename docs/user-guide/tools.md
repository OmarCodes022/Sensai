# Tools and sandbox

The model can ask Sensai to run a tool, then finish its answer with the result.
Use tools for figures you need to trust: a calculation, or a short Python
program on your data files.

## Available tools

```text
> /tools
calculate: Calculate arithmetic using +, -, *, / and parentheses.
run_python: Run Python 3 code in a throw-away folder and return what it prints; data files are in the current folder. Only the standard library is available (csv, statistics, json...; no pandas or numpy).
```

The model decides when to use a tool. Sensai prints one line per tool call and
hides the request itself:

```text
> What is the engagement rate if 630 of 4,200 accounts engaged? Use the calculator.
Using tool: calculate({"expression": "630 / 4200 * 100"})
The engagement rate is 15%.
```

`calculate` accepts numbers, `+`, `-`, `*`, `/` and parentheses, up to 1,024
characters. One message allows five tool calls; after that the model must
answer without tools. When a tool fails, its error goes back to the model,
which can correct itself or explain.

## Run Python

Before running code from the model, Sensai shows it and waits for one key:

```text
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
```

- `y` runs the code, and the model receives its output.
- `n` or Enter refuses: nothing runs, and the model is told
  `tool approval refused`.
- `v` shows the whole code, then asks `[y] run · [n] refuse`. Sensai offers it
  only when the preview is cut.

The preview shows up to 6 lines. Invisible and control characters appear
escaped, so the code can't hide part of itself. Only the standard library is
available: no pandas or numpy. Small models may garble code; a larger model
such as `qwen2.5:7b` works better.

## Give the code your data

Set `SENSAI_DATA_DIR` to a folder. Before each run, Sensai copies the files at
its top level next to the code, up to 50 MB in total:

```bash
SENSAI_DATA_DIR=tests/fixtures .venv/bin/sensai qwen2.5:7b
```

Hidden files (such as `.env`), subfolders, symbolic links and files Python
could import (`.py`, `.pyc`, `.pyw`, `.so`, `.pyd`) are not copied. If the
folder does not exist, Sensai stops at startup with
`error: data folder not found: <path>`.

## Run a file yourself

`/run <file.py>` runs a local UTF-8 file of up to 1 MiB in the same sandbox,
without the model or an approval, and leaves the chat history untouched:

```text
> /run broken.py
Running in the sandbox (limit 15 s)…
Exit code 1 · 0.1 s
stdout:
9
stderr:
Traceback (most recent call last):
  File "main.py", line 4, in <module>
    print(rows[0]["reach"])
          ~~~~~~~^^^^^^^^^
KeyError: 'reach'
```

## Good to know

### Limits of each run

Each run gets a fresh temporary folder, deleted afterwards, with the code as
`main.py`, no keyboard input and almost no environment: none of your `.env`
values, Sensai's settings or API keys.

| Limit | Value | What you see |
| --- | --- | --- |
| Wall-clock time | 15 s | `Time limit reached (15 s)` |
| CPU time | 10 s | `CPU time limit reached` |
| Memory | 512 MB, Linux only | A `MemoryError` traceback |
| Each written file | 10 MB | `File size limit reached (10 MB)` |
| Output | First 10,000 characters of what the code prints, last 10,000 of its errors | `(output truncated)` |
| Data folder | 50 MB in total | `data folder is larger than 50 MB` |

Ctrl+C or Esc stops the code at once: `/run` prints `Exécution interrompue`,
and a chat question prints `Réponse interrompue`.

### What the sandbox does not stop

It stops runaway or careless code, not code written to cause harm. Read the
code before you press `y`:

- The code can use the network and read any file your account can read.
- Code that starts many copies of itself, or programs that detach from it, is
  not stopped.
- On macOS, the memory limit is not enforced, and code can avoid the CPU limit:
  it then runs until the 15 s limit.
- If Sensai is killed abruptly while code runs, for example when the computer
  runs out of memory, programs that code started may keep running. On macOS,
  the code itself may too.
