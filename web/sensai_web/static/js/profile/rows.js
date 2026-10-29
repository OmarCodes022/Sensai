// Profile as a list of key / value rows (the friendly alternative to the JSON editor).
import { h } from '../dom.js';
import { button, iconButton } from '../components/button.js';
import { input, textarea } from '../components/form.js';
import { t } from '../i18n.js';

/** Returns { el, read() } where read() gives { value } or { error } (a strings.* key suffix with args). */
export function profileRows(preferences, onChange = () => {}) {
  const list = h('div', { class: 'stack' });
  const add = (key = '', text = '') => {
    const k = input({ value: key, 'aria-label': t('profile.key'), placeholder: t('profile.key'), class: 'input mono', maxlength: 80, autocomplete: 'off' });
    const v = textarea({ rows: 2, 'aria-label': t('profile.text'), placeholder: t('profile.text') }); v.value = text;
    const row = h('div', { class: 'profile-row' }, k, v, iconButton('trash', t('profile.removeRow'), { variant: 'ghost', size: 'sm', onClick: () => { row.remove(); onChange(); } }));
    row.addEventListener('input', onChange);
    list.append(row);
    return k;
  };
  for (const [k, v] of Object.entries(preferences)) add(k, String(v));
  const more = button(t('profile.addRow'), { icon: 'plus', onClick: () => { add().focus(); onChange(); } });
  const el = h('div', { class: 'stack' }, list, h('div', null, more));
  const read = () => {
    const value = {};
    for (const row of list.children) {
      const [k, v] = [row.querySelector('input').value.trim(), row.querySelector('textarea').value.trim()];
      if (!k && !v) continue;
      if (!k || !v) return { error: 'rowBlank' };
      if (k in value) return { error: 'rowDup', args: { name: k } };
      value[k] = v;
    }
    return { value };
  };
  return { el, read, focusFirst: () => (list.querySelector('input') || add()).focus() };
}
