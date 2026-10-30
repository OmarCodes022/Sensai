// /think in an assistant message: the steps stream in order, then fold into one disclosure (web-ui.md, /think).
import { h } from '../dom.js';
import { chip } from '../components/chip.js';
import { renderInto } from '../markdown.js';
import { announce } from '../a11y.js';
import { getLang, t } from '../i18n.js';

// Section titles are the terminal's English labels (src/sensai/chat/reasoning.py).
const NAMED = new Map([['Plan', 'plan'], ['Act', 'act'], ['Observe', 'observe'], ['Draft', 'draft'], ['Revise', 'revise'], ['Unresolved', 'unresolved'], ['Check unavailable', 'unavailable']]);
const CHECK = /^Check \u2014 (?:ok|(\d+) problems?)$/;
const STATUS_TONE = { ok: 'sage', error: 'rose', refused: 'amber', timeout: 'rose' };

/** A think_section title as { kind, n? }: a step kind, 'ok' or 'problems' for a check, 'final', or 'other'. */
export function stepOf(title) {
  const s = String(title ?? '');
  if (NAMED.has(s)) return { kind: NAMED.get(s) };
  const m = CHECK.exec(s);
  if (m) return m[1] ? { kind: 'problems', n: Number(m[1]) } : { kind: 'ok' };
  return { kind: /^Final answer \(/.test(s) ? 'final' : 'other' };
}

/** "2 rounds", "1 appel d'outil": plural forms of the page language. */
export const counted = (n, key) => t(`think.${key}.${new Intl.PluralRules(getLang()).select(n) === 'one' ? 'one' : 'other'}`, { n });

/** The step label in the page language; a title the page does not know is shown as sent. */
export function stepLabel(title) {
  const s = stepOf(title);
  if (s.kind === 'problems') return t('think.step.problems', { problems: counted(s.n, 'problem') });
  return s.kind === 'other' || s.kind === 'final' ? String(title ?? '') : t(`think.step.${s.kind}`);
}

export const summaryOf = (done) => t('think.summary', { rounds: counted(done.rounds, 'round'), tools: counted(done.tool_calls, 'tool') });

/**
 * The reasoning block. Event order (from the backend): a tool round's tool_call and tool_result come
 * first (the card opens a pending Act step), then the text written before the call, then the Act and
 * Observe sections, each followed by one line (the call, the result) that the card already shows.
 */
export function createReasoning() {
  const list = h('ol', { class: 'reasoning__steps', 'aria-label': t('think.steps') });
  const label = h('summary', { class: 'reasoning__sum' }, t('think.title'));
  const el = h('details', { class: 'reasoning', open: true }, label, list);
  const steps = [];
  let current = null, pending = null, act = null, skip = false, final = false;

  const paint = (s, streaming = true) => { clearTimeout(s.timer); s.timer = null; renderInto(s.body, s.text, { streaming }); };
  const schedule = (s) => { if (!s.timer) s.timer = setTimeout(() => paint(s), 40); };
  function step(kind, title) {
    const head = h('div', { class: 'reasoning__head' }, h('strong', { class: 'reasoning__label' }, stepLabel(title)));
    const body = h('div', { class: 'reasoning__body md', dir: 'auto' });
    const extra = h('div', { class: 'reasoning__extra' });
    const s = { kind, head, body, extra, text: '', card: null, timer: null, li: h('li', { class: 'reasoning__step', dataset: { kind } }, head, body, extra) };
    list.append(s.li); steps.push(s);
    return s;
  }

  return {
    el,
    hasContent: () => steps.length > 0,
    section(title) {
      const s = stepOf(title);
      if (s.kind === 'final') { final = true; current = null; skip = false; return; }
      if (s.kind === 'act' && pending) { current = act = pending; pending = null; }
      else {
        current = step(s.kind, title);
        if (s.kind === 'act') act = current;
      }
      const card = s.kind === 'act' || s.kind === 'observe' ? act?.card : null;
      if (s.kind === 'observe' && card) current.head.append(chip(t(`tool.status.${card.status()}`), { tone: STATUS_TONE[card.status()] }));
      skip = !!card; // Without a card, the call or result line is the only trace: keep it.
      announce(t('think.started', { step: stepLabel(title) }));
    },
    /** Returns false when the text is not part of a step (the final answer, or no step yet). */
    text(delta) {
      if (final || !current) return false;
      if (skip) { skip = false; return true; }
      current.text += delta; schedule(current);
      return true;
    },
    /** A tool card (tool-card.js) opens the round's Act step; the text before the call stays in the step before. */
    addTool(card) { pending = step('act', 'Act'); pending.card = card; pending.extra.append(card.el); },
    /** An approval always shows: a folded block opens first, so the prompt can take focus. */
    addApproval(node) { el.open = true; (pending || act || current || step('act', 'Act')).extra.append(node); },
    /** think_done: fold the steps under "Reasoning: 2 rounds, 1 tool call". */
    done(d) { steps.forEach((s) => paint(s, false)); label.textContent = summaryOf(d); el.open = false; },
    stop() { steps.forEach((s) => paint(s, false)); },
  };
}
