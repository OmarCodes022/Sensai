// User messages, system event dividers and date separators.
import { h } from '../dom.js';
import { icon } from '../icons.js';
import { formatClock, formatDate } from '../format.js';
import { copyButton } from '../components/copy-button.js';
import { button, iconButton } from '../components/button.js';
import { t } from '../i18n.js';

/** opts: { onReuse(text), onEdit(item, text), onRetry(), plannedNote }. With onEdit the pencil edits the message in place. */
export function createUser(item, opts = {}) {
  const num = h('span', { class: 'msg__num num' });
  const note = h('span', { class: 'chip chip--amber', hidden: true }, icon('alert-triangle', { size: 12 }), t('msg.notSent'));
  const retry = h('button', { type: 'button', class: 'btn btn--sm', hidden: true, onclick: () => opts.onRetry?.() }, icon('refresh', { size: 14 }), t('common.retry'));
  const extra = h('div', { class: 'msg__notes' });
  const bubble = h('div', { class: 'bubble', dir: 'auto' }, item.text);
  /** Edit in place: the bubble becomes a box; saving continues from this message in a new conversation. */
  function startEdit() {
    if (el.querySelector('.msg__edit')) return;
    const box = h('textarea', { class: 'textarea', rows: 3, 'aria-label': t('msg.edit') });
    box.value = item.text;
    const done = () => { form.remove(); bubble.hidden = false; };
    const save = () => { const text = box.value.trim(); if (!text) return; done(); opts.onEdit(item, text); };
    const form = h('div', { class: 'msg__edit stack' }, box, h('p', { class: 'muted' }, t('msg.editHint')),
      h('div', { class: 'row' }, button(t('common.cancel'), { size: 'sm', onClick: done }), button(t('msg.editSend'), { variant: 'primary', size: 'sm', onClick: save })));
    box.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') { e.preventDefault(); done(); }
      else if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); save(); }
    });
    bubble.hidden = true; bubble.after(form); box.focus(); box.setSelectionRange(box.value.length, box.value.length);
  }
  const el = h('article', { class: 'msg msg--user', tabindex: '-1' },
    bubble,
    h('div', { class: 'msg__meta' }, note, retry, num, item.at ? h('time', { class: 'msg__time num', datetime: item.at }, formatClock(item.at)) : null,
      copyButton(() => item.text, { label: t('common.copy') }),
      opts.onEdit ? iconButton('edit', t('msg.edit'), { variant: 'ghost', size: 'sm', onClick: () => item.n && startEdit() })
        : iconButton('edit', t('msg.reuse'), { variant: 'ghost', size: 'sm', onClick: () => opts.onReuse?.(item.text) })),
    extra);
  const api = {
    el, item,
    setNumber(n) { item.n = n; num.textContent = `#${n}`; el.dataset.n = String(n); el.setAttribute('aria-label', t('msg.youN', { n })); },
    markNotSent(canRetry) { note.hidden = false; retry.hidden = !canRetry; num.textContent = ''; delete el.dataset.n; el.classList.add('msg--unsent'); },
    clearNotSent() { note.hidden = true; retry.hidden = true; el.classList.remove('msg--unsent'); },
    addNote(node) { extra.append(node); },
  };
  if (item.n) api.setNumber(item.n); else el.setAttribute('aria-label', t('msg.you'));
  return api;
}

export const createEvent = (text) => h('div', { class: 'evt', role: 'note' }, h('span', null, text));
export const createDate = (iso) => h('div', { class: 'evt evt--date', role: 'separator' }, h('time', { datetime: iso }, formatDate(iso)));
export const dayKey = (iso) => (iso ? String(iso).slice(0, 10) : '');
