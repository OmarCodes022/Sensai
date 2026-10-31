// Side detail panel for #/sessions: facts, the /history-style list of the user's messages, Open.
import { h } from '../dom.js';
import { icon } from '../icons.js';
import { button } from '../components/button.js';
import { chip } from '../components/chip.js';
import { emptyState, skeletonRows } from '../components/state.js';
import { formatNumber, formatUtc } from '../format.js';
import { stripInvisible } from '../safetext.js';
import { hrefFor } from '../router.js';
import { sessionButtons } from './manage.js';
import { t } from '../i18n.js';

const firstLine = (s) => { const l = String(s).split('\n')[0]; return l.length > 100 ? `${l.slice(0, 100)} …` : l; };

/** Returns { el, show(session|null) }. onOpen(id) opens the conversation (the view handles the streaming confirm). */
export function createDetail({ api, store, personaName, onOpen, onChange }) {
  const el = h('aside', { class: 'card stack sess-detail', 'aria-label': t('sessions.detail') });
  let seq = 0;
  const hint = () => el.replaceChildren(emptyState({ icon: 'history', title: t('sessions.detailNone'), body: t('sessions.detailHint'), h: 'h3' }));

  async function show(s) {
    const mine = ++seq;
    if (!s) return hint();
    const untitled = !s.title || s.title === '(sans titre)';
    const list = h('div', { class: 'stack' }, skeletonRows(3));
    el.replaceChildren(
      h('h3', { class: untitled ? 'muted' : '' }, /\(branch\)$/.test(s.title || '') ? icon('branch', { size: 16 }) : null, untitled ? t('sessions.untitled') : stripInvisible(s.title)),
      h('div', { class: 'row' }, chip(s.id, { mono: true, outline: true }), s.persona ? chip(personaName(s.persona), { tone: 'accent' }) : null),
      h('dl', { class: 'kv' }, h('dt', null, t('sessions.col.messages')), h('dd', { class: 'num' }, formatNumber(s.messages)),
        h('dt', null, t('sessions.col.created')), h('dd', null, formatUtc(s.created_at)), h('dt', null, t('sessions.col.updated')), h('dd', null, formatUtc(s.updated_at))),
      button(t('sessions.open'), { variant: 'primary', icon: 'external-link', onClick: () => onOpen(s.id) }),
      sessionButtons({ api, store, session: s, done: (kind) => { if (kind === 'delete') hint(); onChange(kind); } }),
      h('h4', null, t('history.title')), list, h('p', { class: 'muted history__note' }, t('history.note')));
    try {
      const full = await api.getSession(s.id);
      if (mine !== seq || !el.isConnected) return;
      const users = (full.items || []).filter((i) => i.kind === 'user');
      list.replaceChildren(users.length ? h('ol', { class: 'history__list' }, users.map((u) => h('li', null, h('a', { class: 'history__row', href: hrefFor('chat', s.id) }, h('span', { class: 'num mono' }, `${u.n}.`), h('span', { dir: 'auto' }, stripInvisible(firstLine(u.text))))))) : h('p', { class: 'muted' }, t('chat.noMessages')));
    } catch (e) {
      if (mine === seq) list.replaceChildren(h('p', { class: 'field__error' }, e.message));
    }
  }
  hint();
  return { el, show };
}
