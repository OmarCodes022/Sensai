import { h, nextId } from '../dom.js';
import { icon } from '../icons.js';
import { rovingTabindex } from '../a11y.js';
import { t } from '../i18n.js';

/** field(label, control, {help, error}) wires label, help and error text to the control. */
export function field(label, control, { help, error } = {}) {
  const id = control.id || (control.id = nextId('f'));
  const wrap = h('div', { class: 'field' }, h('label', { class: 'field__label', for: id }, label), control);
  const ids = [];
  if (help) { const e = h('span', { class: 'field__help', id: `${id}-h` }, help); ids.push(e.id); wrap.append(e); }
  if (error) { const e = h('span', { class: 'field__error', id: `${id}-e` }, icon('alert-triangle', { size: 14 }), error); ids.push(e.id); wrap.append(e); control.setAttribute('aria-invalid', 'true'); }
  if (ids.length) control.setAttribute('aria-describedby', ids.join(' '));
  return wrap;
}

export const input = (attrs) => h('input', { class: 'input', type: 'text', ...attrs });
export const textarea = (attrs) => h('textarea', { class: 'textarea', rows: 3, ...attrs });
export const select = (options, attrs) => h('select', { class: 'select', ...attrs }, options.map(([v, l]) => h('option', { value: v }, l)));

export function toggle(label, { checked, disabled, onChange } = {}) {
  const i = h('input', { type: 'checkbox', role: 'switch', checked, disabled });
  if (onChange) i.addEventListener('change', () => onChange(i.checked));
  return h('label', { class: 'toggle' }, i, h('span', null, label));
}

export function check(label, { type = 'checkbox', name, checked, disabled, indeterminate, onChange } = {}) {
  const i = h('input', { type, name, checked, disabled });
  if (indeterminate) i.indeterminate = true;
  if (onChange) i.addEventListener('change', () => onChange(i.checked));
  return h('label', { class: 'check' }, i, h('span', null, label));
}

/** Search field with clear button. */
export function searchField({ placeholder, label, onInput }) {
  const i = h('input', { class: 'input', type: 'search', placeholder, 'aria-label': label || placeholder });
  const clear = h('button', { type: 'button', class: 'btn btn--ghost btn--icon btn--sm search__clear', 'aria-label': t('common.clear'), hidden: true }, icon('x', { size: 14 }));
  i.addEventListener('input', () => { clear.hidden = !i.value; onInput?.(i.value); });
  clear.addEventListener('click', () => { i.value = ''; clear.hidden = true; onInput?.(''); i.focus(); });
  return Object.assign(h('div', { class: 'search' }, icon('search', { size: 16 }), i, clear), { input: i });
}

/** Segmented control as a radiogroup with roving tabindex. */
export function segmented(label, options, value, onChange) {
  const root = h('div', { class: 'seg', role: 'radiogroup', 'aria-label': label });
  const set = (v) => { root.querySelectorAll('button').forEach((b) => { b.setAttribute('aria-checked', String(b.dataset.v === v)); b.tabIndex = b.dataset.v === v ? 0 : -1; }); };
  for (const [v, l] of options) root.append(h('button', { type: 'button', role: 'radio', dataset: { v } }, l));
  root.addEventListener('click', (e) => { const b = e.target.closest('button'); if (b) { set(b.dataset.v); onChange?.(b.dataset.v); } });
  rovingTabindex(root, 'button', { orientation: 'horizontal', onActivate: (b) => { set(b.dataset.v); onChange?.(b.dataset.v); } });
  set(value);
  return root;
}
