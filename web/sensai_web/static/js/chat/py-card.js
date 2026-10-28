// run_python result body: limit chips, special result lines and Code / Output / Errors tabs (spec 6.8).
import { h } from '../dom.js';
import { chip } from '../components/chip.js';
import { tabs } from '../components/tabs.js';
import { visibleEscapes } from '../safetext.js';
import { formatDuration } from '../format.js';
import { t } from '../i18n.js';

const MAX = 10000;
const LINE = /File "main\.py", line (\d+)/;

function codeLines(code, hl) {
  const pre = h('pre', { class: 'code codelines', tabindex: '0' });
  code.split('\n').forEach((line, i) => pre.append(h('span', { class: 'cl', dataset: { line: i + 1 }, 'aria-current': hl === i + 1 ? 'true' : null }, h('span', { class: 'ln', 'aria-hidden': 'true' }, String(i + 1)), visibleEscapes(line), '\n')));
  return pre;
}

function errorsView(stderr, onLine) {
  const text = stderr.length > MAX ? stderr.slice(-MAX) : stderr;
  const pre = h('pre', { class: 'code', tabindex: '0' });
  text.split('\n').forEach((line, i, all) => {
    const m = line.match(LINE);
    const nl = i < all.length - 1 ? '\n' : '';
    if (!m) return pre.append(visibleEscapes(line), nl);
    pre.append(h('button', { type: 'button', class: 'link-btn mono', 'aria-label': t('py.gotoLine', { n: m[1] }), onclick: () => onLine(Number(m[1])) }, line), nl);
  });
  return pre;
}

/** Returns { el, notes } for a run_python call and its (possibly missing) result. */
export function pythonBody(call, result) {
  const code = String(call.arguments?.code ?? '');
  const m = result?.meta || {};
  const lim = { wall_seconds: 15, cpu_seconds: 10, memory_mb: 512, file_mb: 10, ...(m.limits || {}) };
  const stdout = String(m.stdout ?? result?.output ?? '');
  const stderr = String(m.stderr ?? '');
  let hl = null;
  const notes = [];
  if (m.timed_out) notes.push(t('py.timeLimit', { s: lim.wall_seconds }));
  if (m.cpu_exceeded || /CPU time limit/i.test(stderr)) notes.push(t('py.cpuLimit'));
  if (m.file_exceeded) notes.push(t('py.fileLimit', { mb: lim.file_mb }));
  if (m.signal) notes.push(t('py.signal', { sig: m.signal }));

  const head = h('div', { class: 'row' },
    result ? chip(t('py.exit', { code: typeof m.exit_code === 'number' ? m.exit_code : t('common.na') }), { tone: typeof m.exit_code !== 'number' ? undefined : m.exit_code === 0 ? 'sage' : 'rose', mono: true }) : null,
    result ? chip(formatDuration(result.duration_ms), { outline: true }) : null,
    chip(`${lim.wall_seconds} s`, { outline: true, title: t('py.limitWall') }), chip(`${lim.cpu_seconds} s CPU`, { outline: true, title: t('py.limitCpu') }), chip(`${lim.memory_mb} MB`, { outline: true, title: t('py.limitMem') }));
  const noteEls = notes.map((n) => h('p', { class: 'toolcard__note', role: 'status' }, n));

  let tabEl;
  const items = [{ id: 'code', label: t('py.code'), render: () => codeLines(code, hl) }];
  if (result) {
    items.push({ id: 'output', label: t('py.output'), render: () => h('div', null,
      stdout ? h('pre', { class: 'code', tabindex: '0' }, visibleEscapes(stdout.slice(0, MAX))) : h('p', { class: 'muted' }, t('py.noOutput')),
      m.truncated ? h('p', { class: 'toolcard__note' }, t('py.truncated')) : null) });
    items.push({ id: 'errors', label: stderr ? `${t('py.errors')} *` : t('py.errors'), render: () => (stderr ? errorsView(stderr, (n) => {
      hl = n; tabEl.select('code'); tabEl.querySelector(`[data-line="${n}"]`)?.scrollIntoView({ block: 'center' });
    }) : h('p', { class: 'muted' }, t('py.noErrors'))) });
  }
  tabEl = tabs({ label: t('py.tabs'), items, selected: result ? (stderr && (m.exit_code ?? 0) !== 0 ? 'errors' : 'output') : 'code' });
  return h('div', { class: 'stack' }, head, noteEls, tabEl);
}
