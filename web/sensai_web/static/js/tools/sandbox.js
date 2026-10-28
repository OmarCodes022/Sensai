// Sandbox runner (spec 8.6): the web /run. The file stays in the browser until POST /api/run.
import { h } from '../dom.js';
import { button } from '../components/button.js';
import { progressBar } from '../components/meter.js';
import { pythonBody } from '../chat/py-card.js';
import { limitChips } from './limits.js';
import { formatBytes } from '../format.js';
import { announce } from '../a11y.js';
import { t } from '../i18n.js';

const MAX_BYTES = 1048576;
const SAMPLE = 'import csv\nrows = list(csv.DictReader(open("engagement.csv")))\nprint(len(rows))\n';

/** Maps POST /api/run output to the tool_result shape the run_python card renders. */
export function toResult(r) {
  return { ok: r.exit_code === 0 && !r.timed_out, error: r.report, output: r.stdout, duration_ms: typeof r.duration_s === 'number' ? r.duration_s * 1000 : null,
    meta: { exit_code: r.exit_code, timed_out: r.timed_out, truncated: r.truncated, stdout: r.stdout, stderr: r.stderr, limits: r.limits } };
}

export function createSandbox({ api, store }) {
  const lim = () => store.get().config?.limits?.sandbox || {};
  const ta = h('textarea', { class: 'textarea sandbox__ta', id: 'sandbox-code', rows: 12, spellcheck: 'false', wrap: 'off', 'aria-describedby': 'sandbox-help' });
  ta.value = SAMPLE;
  const gutter = h('pre', { class: 'sandbox__gutter', 'aria-hidden': 'true' });
  const info = h('p', { class: 'muted', role: 'status' });
  const result = h('div', { class: 'stack' });
  const bar = h('div', { class: 'stack', hidden: true });
  const syncGutter = () => {
    const n = ta.value.split('\n').length;
    gutter.textContent = Array.from({ length: n }, (_, i) => i + 1).join('\n');
    const bytes = new TextEncoder().encode(ta.value).length;
    info.textContent = bytes > MAX_BYTES ? t('tools.tooBig', { size: formatBytes(bytes) }) : `${formatBytes(bytes)} / 1 MiB`;
    run.disabled = bytes > MAX_BYTES || !ta.value.trim() || running;
    return bytes;
  };
  ta.addEventListener('input', syncGutter);
  ta.addEventListener('scroll', () => { gutter.scrollTop = ta.scrollTop; });
  let tabEscape = false;
  ta.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { tabEscape = true; return; }
    if (e.key === 'Tab' && !e.shiftKey && !tabEscape) {
      e.preventDefault();
      ta.setRangeText('    ', ta.selectionStart, ta.selectionEnd, 'end'); syncGutter();
    } else if (e.key !== 'Shift') tabEscape = false;
  });

  async function loadFile(file) {
    if (!file) return;
    if (file.size > MAX_BYTES) return info.replaceChildren(t('tools.tooBig', { size: formatBytes(file.size) }));
    try { ta.value = new TextDecoder('utf-8', { fatal: true }).decode(await file.arrayBuffer()); syncGutter(); announce(t('tools.loaded', { name: file.name })); }
    catch { info.textContent = t('tools.notUtf8'); }
  }
  const picker = h('input', { type: 'file', accept: '.py,text/x-python', class: 'sr-only', tabindex: '-1', 'aria-hidden': 'true' });
  picker.addEventListener('change', () => { loadFile(picker.files[0]); picker.value = ''; });
  ta.addEventListener('dragover', (e) => e.preventDefault());
  ta.addEventListener('drop', (e) => { e.preventDefault(); loadFile(e.dataTransfer.files[0]); });

  let running = false, timer = null, token = 0;
  const run = button(t('tools.run'), { variant: 'primary', icon: 'play' });
  const cancel = button(t('common.cancel'), { hidden: true });
  const finish = () => { running = false; clearInterval(timer); bar.hidden = true; cancel.hidden = true; run.removeAttribute('aria-busy'); syncGutter(); };
  run.addEventListener('click', async () => {
    const code = ta.value, mine = ++token, wall = lim().wall_seconds || 15, t0 = performance.now();
    running = true; run.disabled = true; run.setAttribute('aria-busy', 'true'); cancel.hidden = false; result.replaceChildren();
    const label = h('span', { class: 'num' }), prog = h('div', null, progressBar(0));
    bar.hidden = false; bar.replaceChildren(label, prog);
    timer = setInterval(() => {
      const s = (performance.now() - t0) / 1000;
      label.textContent = t('tools.elapsed', { s: s.toFixed(1), max: wall });
      prog.replaceChildren(progressBar(Math.min(100, (s / wall) * 100)));
    }, 200);
    announce(t('tools.running'));
    try {
      const r = await api.run(code);
      if (mine !== token) return;
      result.replaceChildren(r.report ? h('p', { class: 'mono' }, r.report) : null, pythonBody({ arguments: { code } }, toResult({ ...r, limits: { ...lim(), ...(r.limits || {}) } })));
      announce(t('tools.finished'));
    } catch (e) { if (mine === token) result.replaceChildren(h('p', { class: 'field__error', role: 'alert' }, e.message)); }
    if (mine === token) finish();
  });
  cancel.addEventListener('click', () => { token++; finish(); result.replaceChildren(h('p', { class: 'muted', role: 'status' }, t('tools.cancelled'))); });

  const data = h('div', { class: 'stack' });
  api.runData().then((d) => data.replaceChildren(d?.dir ? h('div', { class: 'stack' }, h('p', { class: 'muted' }, t('tools.dataDir', { dir: d.dir })), h('ul', { class: 'bullets' }, (d.files || []).map((f) => h('li', null, h('span', { class: 'mono' }, f.name), ` (${formatBytes(f.bytes)})`)))) : h('p', { class: 'muted' }, t('tools.noData'))))
    .catch((e) => data.replaceChildren(h('p', { class: 'field__error' }, e.message)));

  const el = h('div', { class: 'stack' },
    h('label', { class: 'field__label', for: 'sandbox-code' }, t('tools.codeLabel')),
    h('div', { class: 'sandbox' }, gutter, ta),
    h('p', { class: 'muted', id: 'sandbox-help' }, t('tools.helper')), info,
    h('div', { class: 'row' }, run, cancel, button(t('tools.loadFile'), { onClick: () => picker.click() }), picker),
    bar, limitChips(lim()), result, h('h3', null, t('tools.dataTitle')), data);
  syncGutter();
  return { el, dispose: () => { token++; clearInterval(timer); } };
}
