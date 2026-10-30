// Inline tool card (spec 6.8): one-line collapsed header, expandable body, live status chip.
import { h } from '../dom.js';
import { icon } from '../icons.js';
import { chip } from '../components/chip.js';
import { copyButton } from '../components/copy-button.js';
import { formatDuration } from '../format.js';
import { visibleEscapes, stripInvisible } from '../safetext.js';
import { pythonBody } from './py-card.js';
import { t } from '../i18n.js';

const TONE = { waiting: 'amber', ok: 'sage', error: 'rose', refused: 'amber', timeout: 'rose', stopped: 'rose' };
const first = (s, n = 70) => { const l = String(s).split('\n')[0]; return l.length > n ? `${l.slice(0, n)} …` : l; };

/** Attempt of a tool with a call limit (tool_call / tool_result fields), or null. stopped: past the limit, never run. */
export function attemptOf(...events) {
  const ev = events.find((e) => Number.isInteger(e?.attempt) && Number.isInteger(e?.max_attempts) && e.max_attempts > 0);
  return ev ? { n: ev.attempt, max: ev.max_attempts, last: ev.attempt === ev.max_attempts, stopped: ev.attempt > ev.max_attempts } : null;
}

function summary(call) {
  if (call.name === 'calculate') return String(call.arguments?.expression ?? '');
  if (call.name === 'run_python') return first(call.arguments?.code ?? '');
  return first(JSON.stringify(call.arguments ?? {}));
}

/** opts: { max: tool round limit (null: no limit shown, as in /think), showJson: boolean } */
export function createToolCard(call, opts = {}) {
  let status = 'running', result = null, started = performance.now(), tick = null;
  const statusEl = h('span', { class: 'toolcard__status' });
  const attemptEl = h('span', { class: 'toolcard__attempt' });
  const body = h('div', { class: 'toolcard__body', hidden: true });
  const head = h('button', { type: 'button', class: 'toolcard__head', 'aria-expanded': 'false' },
    icon('wrench', { size: 16 }), h('span', null, t('tool.using')), h('b', { class: 'mono' }, visibleEscapes(String(call.name ?? ''))), h('span', { class: 'toolcard__sum mono truncate' }, visibleEscapes(summary(call))), h('span', { class: 'grow' }), attemptEl, statusEl);
  const el = h('section', { class: 'toolcard', dataset: { status, tool: call.name }, 'aria-label': t('tool.label', { name: stripInvisible(call.name) }) }, head, body);
  head.addEventListener('click', () => { const open = head.getAttribute('aria-expanded') !== 'true'; head.setAttribute('aria-expanded', String(open)); body.hidden = !open; });

  const paintAttempt = () => {
    const a = attemptOf(result, call);
    attemptEl.replaceChildren(...(a && !a.stopped ? [chip(t(a.last ? 'tool.attemptLast' : 'tool.attempt', { n: a.n, max: a.max }), { tone: a.last ? 'amber' : undefined, outline: !a.last })] : []));
  };
  const paintStatus = () => {
    el.dataset.status = status;
    const dur = result ? formatDuration(result.duration_ms) : formatDuration(performance.now() - started);
    const label = t(`tool.status.${status}`);
    statusEl.replaceChildren(...[status === 'running' ? h('span', { class: 'spinner', 'aria-hidden': 'true' }) : null, chip(label, { tone: TONE[status] }), h('span', { class: 'toolcard__dur num' }, status === 'waiting' ? '' : dur)].filter(Boolean));
  };
  const paintBody = () => {
    const kids = [];
    const stopped = status === 'stopped' ? attemptOf(result, call) : null;
    if (stopped) kids.push(h('p', { class: 'toolcard__note toolcard__note--err' }, t('tool.stopped', { max: stopped.max })));
    if (call.name === 'calculate') {
      kids.push(h('div', { class: 'calc' }, h('span', { class: 'calc__expr mono' }, visibleEscapes(summary(call))), h('span', { class: 'calc__eq', 'aria-hidden': 'true' }, '='),
        h('span', { class: 'calc__res num' }, result?.ok ? visibleEscapes(String(result.output).trim()) : t('common.na'))));
    } else if (call.name === 'run_python') kids.push(pythonBody(call, stopped ? null : result));
    if (call.name !== 'run_python' && call.name !== 'calculate' && result?.output) kids.push(h('pre', { class: 'code', tabindex: '0' }, visibleEscapes(String(result.output))));
    if ((call.name !== 'run_python' && call.name !== 'calculate') || opts.showJson) {
      const json = JSON.stringify(call.arguments ?? {}, null, 2);
      kids.push(h('div', { class: 'stack' }, h('div', { class: 'row' }, h('strong', null, t('tool.arguments')), copyButton(() => json, { label: t('common.copy') })), h('pre', { class: 'code', tabindex: '0' }, visibleEscapes(json))));
    }
    if (status === 'refused') kids.push(h('p', { class: 'toolcard__note' }, t('approval.refused')));
    else if (status === 'timeout' && call.name !== 'run_python') kids.push(h('p', { class: 'toolcard__note' }, t('tool.timedOut', { s: 30 })));
    else if (status === 'error' && result?.error && call.name !== 'run_python') kids.push(h('p', { class: 'toolcard__note toolcard__note--err mono' }, visibleEscapes(String(result.error))));
    else if (status === 'error' && result?.error) kids.push(h('p', { class: 'muted mono' }, visibleEscapes(String(result.error))));
    kids.push(h('p', { class: 'muted toolcard__meta' }, opts.max === null ? t('tool.roundN', { n: call.round ?? 1 }) : t('tool.round', { n: call.round ?? 1, max: opts.max ?? 5 }), result ? ` · ${formatDuration(result.duration_ms)}` : ''));
    body.replaceChildren(...kids);
  };
  const render = () => { paintAttempt(); paintStatus(); paintBody(); };
  tick = setInterval(() => { if (status === 'running') paintStatus(); }, 500);

  const card = {
    el, call, status: () => status,
    setStatus(s) { if (status === 'refused' && s !== 'refused') return; status = s; render(); },
    setResult(r) {
      result = r; clearInterval(tick);
      if (status !== 'refused') status = r.ok ? 'ok' : attemptOf(r, call)?.stopped ? 'stopped' : r.meta?.timed_out ? 'timeout' : 'error';
      render();
    },
    cancel() { clearInterval(tick); if (!result && status !== 'refused') { status = 'cancelled'; render(); } },
    expand() { head.setAttribute('aria-expanded', 'true'); body.hidden = false; },
  };
  render();
  return card;
}

/** Card for a stored tool item (restored sessions). */
export function toolCardFromItem(item, opts) {
  const c = createToolCard({ id: item.id, name: item.name, arguments: item.arguments, round: item.round, attempt: item.attempt, max_attempts: item.max_attempts }, opts);
  if (item.refused) c.setStatus('refused');
  if (item.ok !== null && item.ok !== undefined) c.setResult({ ok: item.ok, error: item.error, output: item.output, duration_ms: item.duration_ms, meta: item.meta });
  else c.cancel();
  return c;
}
