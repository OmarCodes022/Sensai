// /search <query> in the chat (T3): the top web results as a card; nothing is sent to the model.
import { h } from '../dom.js';
import { t } from '../i18n.js';

export function createSearchCommand({ api, transcript }) {
  const show = (node) => { transcript.append(node, new Date().toISOString()); transcript.scrollToBottom(); };
  const card = (title, ...kids) => h('section', { class: 'card stack doccmd', role: 'status' }, h('strong', null, title), ...kids);
  return async function search(query = '') {
    if (!query.trim()) return show(card(t('search.usage')));
    try {
      const r = await api.webSearch(query);
      show(card(t('search.title', { q: r.query }), h('p', { class: 'muted' }, t('search.noModel')),
        ...(r.items.length ? r.items.map((x) => h('div', { class: 'stack' },
          h('div', { class: 'row' }, h('span', { class: 'num mono' }, `[${x.n}]`), h('a', { href: x.url, target: '_blank', rel: 'noopener noreferrer' }, x.title)),
          h('p', { class: 'muted' }, x.snippet))) : [h('p', { class: 'muted' }, t('search.none'))])));
    } catch (e) { show(card(t('search.failed'), h('p', { class: 'field__error', role: 'alert' }, e.message))); }
  };
}
