// Blocking approval card (spec 6.9). Refuse is the default everywhere; a 400 ms guard ignores stale key presses.
import { h } from '../dom.js';
import { icon } from '../icons.js';
import { chip } from '../components/chip.js';
import { kbd } from '../components/meter.js';
import { trapFocus } from '../a11y.js';
import { stripInvisible } from '../safetext.js';
import { previewView } from './preview.js';
import { t } from '../i18n.js';

export const GUARD_MS = 400;

const fullLines = (args = {}) => Object.entries(args).flatMap(([name, v]) =>
  String(typeof v === 'string' ? v : JSON.stringify(v)).split('\n').map((text) => ({ header: `${name}:`, text })));

/** req: approval_request event. deps: { getCall(callId), onDecide(approved): Promise }. */
export function createApproval(req, { getCall, onDecide }) {
  const mounted = performance.now();
  let decided = false, expanded = false, release = null, settledNote = null;
  const action = stripInvisible(req.action).replace(/^run_/, '');
  const uid = `ap-${req.id}`;
  const previewBox = h('div');
  const note = h('p', { class: 'approval__note', hidden: true }, icon('alert-triangle', { size: 14 }), t('approval.incomplete'));
  const err = h('p', { class: 'field__error', role: 'alert', hidden: true });
  const paused = chip(t('approval.paused'), { tone: 'amber', icon: 'pause' });
  const run = h('button', { type: 'button', class: 'btn btn--primary approval__run', 'aria-disabled': 'true', 'aria-keyshortcuts': 'y' }, h('span', { class: 'approval__unlock', 'aria-hidden': 'true' }), t('common.run'), ...kbd('Y'));
  const refuse = h('button', { type: 'button', class: 'btn approval__refuse', 'aria-keyshortcuts': 'n' }, t('common.refuse'), ...kbd('N'));
  const more = h('button', { type: 'button', class: 'btn btn--ghost', 'aria-keyshortcuts': 'v', hidden: true }, t('common.viewAll'), ...kbd('V'));
  const el = h('section', { class: 'approval', role: 'alertdialog', 'aria-labelledby': `${uid}-t`, 'aria-describedby': `${uid}-r`, tabindex: '-1', dataset: { id: req.id } },
    h('div', { class: 'row' }, icon('shield-check', { size: 20 }), h('h3', { id: `${uid}-t` }, t('approval.title', { action })), h('span', { class: 'grow' }), paused),
    h('p', { id: `${uid}-r` }, stripInvisible(req.reason || t(String(req.action).includes('.') ? 'approval.reasonMcp' : 'approval.reason'))), previewBox, note,
    req.action === 'run_python' ? h('p', { class: 'approval__honesty' }, t('approval.honesty')) : null, err,
    h('div', { class: 'approval__foot' }, run, refuse, more));

  const paint = () => {
    const full = expanded ? fullLines(getCall(req.call_id)?.arguments) : null;
    const v = previewView(req.preview || { lines: [] }, { expanded, full: full?.length ? full : null });
    previewBox.replaceChildren(v.el);
    note.hidden = !v.incomplete;
    more.hidden = expanded || !v.incomplete;
  };
  paint();

  const settle = (approved, quiet = false) => {
    if (el.classList.contains('approval--done')) return;
    decided = true; release?.(); cleanup();
    el.classList.add('approval--done');
    el.setAttribute('role', 'status');
    el.replaceChildren(h('div', { class: 'row' }, icon(approved ? 'check-circle' : 'x-circle', { size: 18 }),
      h('strong', null, t('approval.title', { action })), chip(approved ? t('approval.approved') : t('approval.refusedShort'), { tone: approved ? 'sage' : 'amber' }),
      (settledNote = h('span', { class: 'muted', role: 'status' }, approved ? t('approval.running') : t('approval.refused')))));
    if (!quiet && (document.activeElement === document.body || el.contains(document.activeElement) || !document.activeElement)) el.focus();
  };
  async function decide(approved) {
    if (decided) return;
    if (approved && performance.now() - mounted < GUARD_MS) return;
    decided = true;
    run.setAttribute('aria-disabled', 'true'); refuse.disabled = true;
    try { await onDecide(approved); settle(approved); }
    catch (e) { decided = false; refuse.disabled = false; run.removeAttribute('aria-disabled'); err.hidden = false; err.textContent = e.message; }
  }
  const viewAll = () => { if (!more.hidden) { expanded = true; paint(); } };

  const onKey = (e) => {
    if (decided || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); decide(false); return; }
    if (e.target.matches?.('input, textarea, select, [contenteditable]')) return;
    if (performance.now() - mounted < GUARD_MS) return;
    const k = e.key.toLowerCase();
    if (k === 'y') decide(true); else if (k === 'n') decide(false); else if (k === 'v') viewAll();
  };
  const onHide = () => { if (!decided) onDecide(false).catch(() => {}); };
  document.addEventListener('keydown', onKey, true);
  addEventListener('pagehide', onHide);
  const cleanup = () => { document.removeEventListener('keydown', onKey, true); removeEventListener('pagehide', onHide); };

  run.addEventListener('click', () => decide(true));
  refuse.addEventListener('click', () => decide(false));
  more.addEventListener('click', viewAll);
  setTimeout(() => run.removeAttribute('aria-disabled'), GUARD_MS);
  if (matchMedia('(max-width: 767px)').matches) { el.classList.add('approval--sheet'); queueMicrotask(() => { release = trapFocus(el); }); }

  /** Called when the approved call's result arrives, so the card no longer says it is still running. */
  const finished = (ok) => { if (settledNote && el.classList.contains('approval--done')) settledNote.textContent = ok ? t('approval.ranOk') : t('approval.ranFail'); };
  return { el, id: req.id, focus: () => refuse.focus(), settle, finished, dispose: () => { cleanup(); release?.(); }, isOpen: () => !decided && !el.classList.contains('approval--done') };
}
