import { h } from '../dom.js';

let box;
const live = new Map();

/** toast(text, {tone, action:{label,onClick}, timeout}). Max 3 stacked; identical text is deduped. */
export function toast(text, { tone, action, timeout = 5000 } = {}) {
  if (!box) { box = h('div', { class: 'toasts' }); document.body.append(box); }
  if (live.has(text)) { live.get(text).restart(); return; }
  let timer, hovered = false;
  const remove = () => { clearTimeout(timer); live.delete(text); el.remove(); };
  const restart = () => { clearTimeout(timer); timer = setTimeout(() => { if (!hovered) remove(); }, timeout); };
  const el = h('div', { class: `toast ${tone ? `toast--${tone}` : ''}`, role: 'status', dataset: { text } }, h('span', { class: 'toast__text' }, text),
    action ? h('button', { type: 'button', class: 'btn btn--sm', onclick: () => { action.onClick(); remove(); } }, action.label) : null);
  el.addEventListener('pointerenter', () => { hovered = true; clearTimeout(timer); });
  el.addEventListener('pointerleave', () => { hovered = false; restart(); });
  el.addEventListener('focusin', () => { hovered = true; clearTimeout(timer); });
  el.addEventListener('focusout', () => { hovered = false; restart(); });
  box.append(el);
  live.set(text, { restart, remove });
  restart();
  while (box.children.length > 3) live.get(box.firstElementChild.dataset.text).remove();
}
