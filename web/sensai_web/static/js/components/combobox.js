import { h, nextId } from '../dom.js';

/** ARIA 1.2 combobox with listbox popup and aria-activedescendant. options: [{value,label,disabled}] */
export function combobox({ label, options, value = '', onSelect, placeholder }) {
  const id = nextId('cb');
  const input = h('input', { class: 'input', role: 'combobox', 'aria-label': label, 'aria-expanded': 'false', 'aria-controls': `${id}-lb`, 'aria-autocomplete': 'list', autocomplete: 'off', placeholder });
  const list = h('div', { class: 'listbox', role: 'listbox', id: `${id}-lb`, 'aria-label': label, hidden: true });
  let shown = [], active = -1;
  const paint = () => {
    list.replaceChildren(...shown.map((o, i) => h('div', { class: 'option', role: 'option', id: `${id}-o${i}`, 'aria-selected': String(o.value === value), 'aria-disabled': o.disabled ? 'true' : null, 'data-active': String(i === active) }, o.label)));
    input.setAttribute('aria-activedescendant', active >= 0 ? `${id}-o${active}` : '');
  };
  const open = (q = '') => {
    shown = options.filter((o) => o.label.toLowerCase().includes(q.toLowerCase()));
    active = shown.length ? 0 : -1;
    list.hidden = false; input.setAttribute('aria-expanded', 'true'); paint();
  };
  const close = () => { list.hidden = true; input.setAttribute('aria-expanded', 'false'); input.setAttribute('aria-activedescendant', ''); };
  const pick = (i) => { const o = shown[i]; if (!o || o.disabled) return; value = o.value; input.value = o.label; close(); onSelect?.(o.value); };
  input.addEventListener('input', () => open(input.value));
  input.addEventListener('focus', () => open(''));
  input.addEventListener('blur', () => setTimeout(close, 120));
  input.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); if (list.hidden) open(input.value); else { active = (active + 1) % shown.length; paint(); } }
    else if (e.key === 'ArrowUp') { e.preventDefault(); active = (active - 1 + shown.length) % shown.length; paint(); }
    else if (e.key === 'Enter' && !list.hidden) { e.preventDefault(); pick(active); }
    else if (e.key === 'Escape' && !list.hidden) { e.stopPropagation(); close(); }
  });
  list.addEventListener('pointerdown', (e) => { e.preventDefault(); const i = [...list.children].indexOf(e.target.closest('.option')); if (i >= 0) pick(i); });
  const cur = options.find((o) => o.value === value);
  if (cur) input.value = cur.label;
  return h('div', { class: 'combo' }, input, list);
}
