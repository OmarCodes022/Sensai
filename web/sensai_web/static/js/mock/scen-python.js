// Scenarios 4-8, 30-31: run_python with approval (success, refused, runtime error, limits, hostile preview, fix, stop).
import { PY_CODE, PY_CODE_BAD } from './fixtures.js';
import { say, usage, title, turn, call, result, approval } from './script.js';

const WALL = { wall_seconds: 15, cpu_seconds: 10, memory_mb: 512 };
const STOP = 'Stopped after 3 attempts: answer with the last result or error, without calling run_python again.';
// Attempt n of run_python's 3 per question, on its tool_call and tool_result (web/web-ui.md).
const run = (n) => ({ attempt: n, max_attempts: 3 });
const ask = (code, onYes, onNo, extra, n = 1) => [call(`c${n}`, 'run_python', { code }, n, run(n)), approval(`a${n}`, `c${n}`, code, onYes, onNo, extra)];
const refusedRun = (n = 1) => result(`c${n}`, 'run_python', false, { error: 'tool approval refused', duration_ms: 0, delay_ms: 150, ...run(n) });
const refused = [refusedRun(),
  say('Understood, I will not run any code. From the weekly figures you gave me, 630 of 4,200 accounts engaged, which is **15.0%**. I could not compute the daily average without the file.'), usage(301, 58)];
// A failed run's error as the page receives it: the model's report without its fix-it line.
const report = (stdout, { exit_code: code = 0, ms = 300, stderr = '' }) => [`Exit code ${code} · ${(ms / 1000).toFixed(1)} s`,
  ...(stdout ? ['stdout:', stdout.trimEnd()] : []), ...(stderr ? ['stderr:', stderr.trimEnd()] : [])].join('\n');
const ran = (stdout, meta = {}, n = 1) => result(`c${n}`, 'run_python', (meta.exit_code ?? 0) === 0, {
  error: meta.exit_code ? report(stdout, meta) : null, output: stdout, duration_ms: meta.ms ?? 300, ...run(n),
  meta: { exit_code: 0, timed_out: false, truncated: false, stdout, stderr: '', limits: WALL, ...meta } });

const stderr6 = 'Traceback (most recent call last):\n  File "main.py", line 4, in <module>\n    reach.append(int(row["reach"]))\n           ~~~^^^^^^^^^\nKeyError: \'reach\'\n';
const zeroErr = (line, kind = '') => `Traceback (most recent call last):\n  File "main.py", line ${line}, in <module>\n    print(engaged / reached * 100)\n          ~~~~~~~~^~~~~~~~~\nZeroDivisionError: ${kind}division by zero\n`;
const DAY28 = 'import csv\nrow = [r for r in csv.DictReader(open("engagement.csv")) if r["date"] == "2026-09-28"][0]\nengaged, reached = int(row["accounts_engaged"]), int(row["accounts_reached"])\nprint(engaged / reached * 100)';
const DAY28B = DAY28.replace('[0]', '[-1]');
const DAY28C = `${DAY28.split('\n').slice(0, 3).join('\n')}\nreached = float(reached)\nprint(engaged / reached * 100)`;
const failed = (n, line, kind) => ran('', { exit_code: 1, stderr: zeroErr(line, kind), ms: 190 }, n);
const tryAgain = (n, code, onYes) => ask(code, onYes, [refusedRun(n), say('Understood, no more runs.'), usage(300, 10)], undefined, n);
const loop = 'import time\nwhile True:\n    time.sleep(0.01)';
const flood = 'print("x" * 10_000_000)';
const hostile = 'print("all clear")\n# \x1b[2J\x1b[H hidden clear-screen\nname = "admin‮⁦ gnirts"\nprint(name)\nimport os\nos.system("echo done")';
const hostileLines = ['print("all clear")', '# \\x1b[2J\\x1b[H hidden clear-screen', 'name = "admin\\u202e\\u2066 gnirts"', 'print(name)', 'import os', 'os.system("echo done")']
  .map((text) => ({ header: 'code:', text }));

export const PYTHON = [
  { id: 'py-ok', n: 4, title: 'run_python approved: success', persona: 'analyse', prompt: 'What was the average daily reach from 21 to 27 September?', notes: 'Press y to run, n to refuse, v to view all.',
    turns: [turn(null, [say('I will compute this from engagement.csv, using the daily rows only. '), ask(PY_CODE,
      [ran('1021.4\n', { ms: 300 }), say('The average daily reach from 21 to 27 September is **1,021.4** accounts. I used the daily rows only, not the weekly unique row.'), title('Average daily reach'), usage(318, 74, 4100, 3900)],
      refused)])] },
  { id: 'py-refused', n: 5, title: 'run_python refused', persona: 'analyse', prompt: 'Compute the average reach with a script', notes: 'Answer n. The model is told and answers without code.',
    turns: [turn(null, [say('A short script will do this. '), ask(PY_CODE, [ran('1021.4\n'), say('Average daily reach: **1,021.4**.'), usage(300, 40)], refused)])] },
  { id: 'py-error', n: 6, title: 'run_python runtime error', persona: 'analyse', prompt: 'Compute the average reach from the CSV', notes: 'Approve, then open the Errors tab and click the line link.',
    turns: [turn(null, [say('Running a quick script. '), ask(PY_CODE_BAD, [
      ran('', { exit_code: 1, stderr: stderr6, ms: 210 }),
      say('The script failed with a `KeyError`: the column is named `accounts_reached`, not `reach`. Shall I try again with the right column?'), usage(340, 62)], refused)])] },
  { id: 'py-limits', n: 7, title: 'run_python limits (two turns)', persona: 'analyse', prompt: 'Run a loop that waits forever (then ask for a huge print)', notes: 'Turn 1 hits the wall clock. Turn 2 floods stdout.',
    turns: [
      turn(null, [say('Here is the loop you asked for. '), ask(loop, [result('c1', 'run_python', false, { error: 'Exit code -9 · 15.0 s\nTime limit reached (15 s)', duration_ms: 15000, ...run(1), meta: { exit_code: -9, timed_out: true, truncated: false, stdout: '', stderr: '', signal: 'SIGKILL', limits: WALL } }),
        say('The loop never ends, so the sandbox stopped it after 15 s.'), usage(210, 30)], refused)]),
      turn(null, [say('Now a very large print. '), ask(flood, [ran('x'.repeat(10000), { truncated: true, ms: 1800 }), say('The output was cut at 10,000 characters.'), usage(220, 28)], refused)])] },
  { id: 'py-hostile', n: 8, title: 'Hostile preview', persona: 'analyse', prompt: 'Run the cleanup script', notes: 'Escapes and the bidi override are shown as visible chips.',
    turns: [turn(null, [say('Here is the script. '), ask(hostile, [ran('all clear\nadmin string\ndone\n'), say('Done.'), usage(200, 12)], refused,
      { preview: { lines: hostileLines, hidden_lines: 0, incomplete: false } })])] },
  { id: 'py-fix', n: 30, title: 'run_python fixes its own code', persona: 'analyse', prompt: 'What was the average daily reach from 21 to 27 September?', notes: 'Approve twice. Run 1 of 3 fails with a KeyError, the model reads it and Run 2 of 3 succeeds.',
    turns: [turn(null, [say('I will compute this from engagement.csv. '), ask(PY_CODE_BAD, [
      ran('', { exit_code: 1, stderr: stderr6, ms: 210 }),
      say('The column is named `accounts_reached`, not `reach`. Fixing the script. '), tryAgain(2, PY_CODE, [ran('1021.4\n', { ms: 280 }, 2),
        say('The average daily reach from 21 to 27 September is **1,021.4** accounts. The first run failed on a wrong column name; the second one worked.'), title('Average daily reach'), usage(512, 96)])],
    refused)])] },
  { id: 'py-stop', n: 31, title: 'run_python stops after 3 attempts', persona: 'analyse', prompt: 'What was the engagement rate on 28 September?', notes: 'Approve three times. Run 3 of 3 says it is the last; the fourth call is not run and the model reports the error.',
    turns: [turn(null, [say('Computing the rate for 28 September. '), ask(DAY28, [failed(1, 4), say('Division by zero. Let me check the row again. '),
      tryAgain(2, DAY28B, [failed(2, 4), say('Still zero. Trying a float. '), tryAgain(3, DAY28C, [failed(3, 5, 'float '),
        call('c4', 'run_python', { code: DAY28C }, 4, run(4)), result('c4', 'run_python', false, { error: STOP, duration_ms: 0, delay_ms: 150, ...run(4) }),
        say('I could not compute it: on 28 September the reach is **0**, so the rate is undefined (n/a). The last run failed with `ZeroDivisionError: float division by zero`.'), usage(640, 70)])])],
    refused)])] },
];
