// /history popover: the creator's own messages, numbered like the CLI (spec 6.5).
import { h } from '../dom.js';
import { openPopover } from '../components/popover.js';
import { skeletonRows } from '../components/state.js';
import { t } from '../i18n.js';

/** anchor: element to attach to. onPick(n) scrolls the transcript to message n. */
export function openHistory(anchor, { api, canEdit, onPick }) {
  const box = h('div', { class: 'stack history' }, h('h3', null, t('history.title')), skeletonRows(3));
  const pop = openPopover(anchor, box, { label: t('history.title') });
  api.history().then(({ items }) => {
    const list = items.length ? h('ol', { class: 'history__list' }, items.map((it) => h('li', null,
      h('button', { type: 'button', class: 'history__row', onclick: () => { pop.close(); onPick(it.n); } }, h('span', { class: 'num mono' }, `${it.n}.`), h('span', { dir: 'auto' }, it.text))))) : h('p', { class: 'muted' }, t('chat.noMessages'));
    box.replaceChildren(h('h3', null, t('history.title')), list, h('p', { class: 'muted history__note' }, t('history.note'), canEdit ? ` ${t('history.noteEdit')}` : ''));
    pop.place();
  }).catch((e) => { box.replaceChildren(h('p', { class: 'field__error' }, e.message)); });
  return pop;
}
