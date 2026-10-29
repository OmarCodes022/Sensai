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
characters. One message allows five tool rounds; after that the model must
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
Using tool: run_python · Run 1 · Exit code 0 · 0.3 s
1021.4
The average daily reach from 21 to 27 Sep was 1021.4 accounts.
```

Sensai numbers each run of the question (`Run 1`), then prints the exit code
and the last line the code printed. When the code fails, that second line is
the last line of the error instead.

- `y` runs the code, and the model receives its output.
- `n` or Enter refuses: nothing runs, Sensai prints
  `Using tool: run_python · Run 1 · tool approval refused`, and the model is
  told `tool approval refused`.
- `v` shows the whole code, then asks `[y] run · [n] refuse`. Sensai offers it
  only when the preview is cut.

The preview shows up to 6 lines. Invisible and control characters appear
escaped, so the code can't hide part of itself. Only the standard library is
available: no pandas or numpy. Small models may garble code; a larger model
such as `qwen2.5:7b` works better.

## When the code fails

The model reads the error and fixes its own code. Sensai asks again before
each new try:

```text
> What was the average engagement rate from 21 to 27 Sep? Compute it with Python.
Run run_python?
  code:
    import csv
    rows = list(csv.DictReader(open("engagement.csv")))
    print(rows[0]["engaged"])
[y] run · [n] refuse y
Using tool: run_python · Run 1 · Exit code 1 · 0.1 s
KeyError: 'engaged'
Run run_python?
  code:
    import csv
    rows = [r for r in csv.DictReader(open("engagement.csv"))
            if r["source"] == "instagram_insights_daily" and "2026-09-21" <= r["date"] <= "2026-09-27"]
    print(round(sum(float(r["engagement_rate"]) for r in rows) / len(rows), 1))
[y] run · [n] refuse y
Using tool: run_python · Run 2 · Exit code 0 · 0.1 s
11.7
The average daily engagement rate from 21 to 27 Sep was 11.7%.
```

The model gets 3 runs per question. The report of the 3rd ends with
`This was the last attempt: answer with this result or error, without calling run_python again.`
A 4th call runs nothing: Sensai prints
`Using tool: run_python · Stopped after 3 attempts`, and the model must answer
with the last error instead of guessing. The chat goes on, and the next
question starts again at `Run 1`. Every run, refused ones included, also
counts toward the five tool rounds of the question.

After each run, the model receives a short report, not the whole output:

```text
Attempt 1 of 3 · Exit code 1 · 0.1 s
stderr:
Traceback (most recent call last):
  File "main.py", line 3, in <module>
    print(rows[0]["engaged"])
          ~~~~~~~^^^^^^^^^^^
KeyError: 'engaged'
If it failed, fix the code and call run_python again; otherwise answer using this output.
```

It holds the exit code, any limit reached, and the last 2,000 characters of
what the code printed and of its errors. A cut stream is labelled
`stdout (last 2000 characters):` and the report says `(output truncated)`.
When the code printed more than the 10,000 characters Sensai keeps, the end
of its output is lost, so the label gives the position of the part shown
instead, such as `stdout (characters 8001-10000; the rest was not captured):`.
The code, these reports and the answer are saved with the session like any
other exchange, so `--session <id>` brings them back. `/run` still prints the
full result shown in [Run a file yourself](#run-a-file-yourself), without this
report.

The second line of `Using tool: run_python` is read from the report, so a line
the code prints itself, such as `stderr:`, can change which line is shown
there; it is always shown with control characters escaped.

## Give the code your data

Set `SENSAI_DATA_DIR` to a folder. Before each run, Sensai copies the files at
its top level next to the code, up to 50 MB in total:

```bash
SENSAI_DATA_DIR=tests/fixtures .venv/bin/sensai qwen2.5:7b
```

Hidden files (such as `.env`), files whose name holds a line break or another
non-printable character, subfolders, symbolic links and files Python
could import (`.py`, `.pyc`, `.pyw`, `.so`, `.pyd`) are not copied, and the
model is never told their names. If the
folder does not exist, Sensai stops at startup with
`error: data folder not found: <path>`, and if it cannot be read, with
`error: cannot read data folder: …`.

At startup, Sensai tells the model the names of these files, never their
contents, for example
`Data files available to run_python: brand.json, dms.json, engagement.csv, posts.json.`
An empty folder gives `The data folder has no files run_python can use.` The
names stay in the instructions after `/persona` and when a session is resumed.

Sensai checks each file before copying it. Today every file is allowed; once
file permissions exist, a file that is not allowed will not be copied, and the
model will read `Not available (not allowed): <names>` in its report.

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
