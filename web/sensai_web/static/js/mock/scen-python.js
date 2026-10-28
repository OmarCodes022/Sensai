// Scenarios 4-8: run_python with approval (success, refused, runtime error, limits, hostile preview).
import { PY_CODE, PY_CODE_BAD } from './fixtures.js';
import { say, usage, title, turn, call, result, approval } from './script.js';

const WALL = { wall_seconds: 15, cpu_seconds: 10, memory_mb: 512 };
const ask = (code, onYes, onNo, extra) => [call('c1', 'run_python', { code }), approval('a1', 'c1', code, onYes, onNo, extra)];
const refused = [result('c1', 'run_python', false, { error: 'refused by user', duration_ms: 0, delay_ms: 150 }),
  say('Understood, I will not run any code. From the weekly figures you gave me, 630 of 4,200 accounts engaged, which is **15.0%**. I could not compute the daily average without the file.'), usage(301, 58)];
const ran = (stdout, meta = {}) => result('c1', 'run_python', (meta.exit_code ?? 0) === 0, {
  error: meta.exit_code ? `Exit code ${meta.exit_code}` : null, output: stdout, duration_ms: meta.ms ?? 300,
  meta: { exit_code: 0, timed_out: false, truncated: false, stdout, stderr: '', limits: WALL, ...meta } });

const stderr6 = 'Traceback (most recent call last):\n  File "main.py", line 4, in <module>\n    reach.append(int(row["reach"]))\n           ~~~^^^^^^^^^\nKeyError: \'reach\'\n';
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
      turn(null, [say('Here is the loop you asked for. '), ask(loop, [result('c1', 'run_python', false, { error: 'Time limit reached (15 s)', duration_ms: 15000, meta: { exit_code: -9, timed_out: true, truncated: false, stdout: '', stderr: '', signal: 'SIGKILL', limits: WALL } }),
        say('The loop never ends, so the sandbox stopped it after 15 s.'), usage(210, 30)], refused)]),
      turn(null, [say('Now a very large print. '), ask(flood, [ran('x'.repeat(10000), { truncated: true, ms: 1800 }), say('The output was cut at 10,000 characters.'), usage(220, 28)], refused)])] },
  { id: 'py-hostile', n: 8, title: 'Hostile preview', persona: 'analyse', prompt: 'Run the cleanup script', notes: 'Escapes and the bidi override are shown as visible chips.',
    turns: [turn(null, [say('Here is the script. '), ask(hostile, [ran('all clear\nadmin string\ndone\n'), say('Done.'), usage(200, 12)], refused,
      { preview: { lines: hostileLines, hidden_lines: 0, incomplete: false } })])] },
];
