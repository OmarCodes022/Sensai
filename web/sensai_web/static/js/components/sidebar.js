import { h } from '../dom.js';
import { icon } from '../icons.js';
import { button } from './button.js';
import { chip } from './chip.js';
import { searchField } from './form.js';
import { emptyState, errorState, skeletonRows } from './state.js';
import { rovingTabindex } from '../a11y.js';
import { dayGroup, relativeTime, formatUtc } from '../format.js';
import { stripInvisible } from '../safetext.js';
import { ROUTES, hrefFor } from '../router.js';
import { t } from '../i18n.js';

export function createSidebar({ store, actions, router }) {
  let query = '';
  const search = searchField({ placeholder: t('sessions.search'), label: t('sessions.search'), onInput: (v) => { query = v.trim().toLowerCase(); paint(); } });
  const list = h('div', { class: 'sb-list', role: 'list' });
  const newBtn = button(t('chat.new'), { variant: 'primary', icon: 'plus', onClick: actions.newChat, 'aria-keyshortcuts': 'Control+Shift+O' });
  newBtn.classList.add('btn--lg');
  const navLinks = h('nav', { 'aria-label': t('nav.views') });
  const foot = h('div', { class: 'sb-foot' }, h('details', { open: true }, h('summary', null, icon('grid', { size: 16 }), t('nav.views')), navLinks), h('span', { class: 'muted' }, t('everything.local')));
  const root = h('nav', { class: 'sidebar', 'aria-label': t('sessions.title') }, newBtn, h('div', { class: 'sb-search' }, search), list, foot);
  const rover = rovingTabindex(list, 'a.sess', { orientation: 'vertical' });

  list.addEventListener('click', async (e) => {
    const a = e.target.closest('a.sess');
    if (!a || !store.get().status.streaming) return;
    e.preventDefault();
    if (await actions.confirmStop()) location.hash = a.getAttribute('href');
  });
  search.input.addEventListener('keydown', (e) => { if (e.key === 'ArrowDown') list.querySelector('a.sess')?.focus(); });
  root.addEventListener('keydown', (e) => { if (e.key === '/' && !e.target.matches('input,textarea')) { e.preventDefault(); search.input.focus(); } });

  function row(s) {
    const untitled = !s.title || s.title === '(sans titre)';
    const cur = store.get().session?.id === s.id;
    const branch = /\(branch\)$/.test(s.title || '');
    return h('a', { class: 'sess', role: 'listitem', href: hrefFor('chat', s.id), 'aria-current': cur ? 'page' : null },
      h('div', { class: `sess__title truncate ${untitled ? 'is-untitled' : ''}`, 'data-tip': untitled ? null : stripInvisible(s.title) }, branch ? icon('branch', { size: 12 }) : null, untitled ? t('sessions.untitled') : stripInvisible(s.title)),
      h('div', { class: 'sess__meta' }, h('span', { class: 'mono' }, s.id), s.persona ? chip(store.get().personas.find((p) => p.id === s.persona)?.name || s.persona, { tone: 'accent' }) : null,
        h('time', { datetime: s.updated_at, 'data-tip': formatUtc(s.updated_at) }, relativeTime(s.updated_at))));
  }

  function paint() {
    const { items, state } = store.get().sessions;
    list.removeAttribute('role');
    if (state === 'loading' && !items.length) return list.replaceChildren(skeletonRows(6));
    if (state === 'error') return list.replaceChildren(errorState({ title: t('sessions.loadError'), onRetry: () => actions.refreshSessions() }));
    const shown = items.filter((s) => !query || `${s.title || ''} ${s.id}`.toLowerCase().includes(query)).sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at)));
    if (!shown.length) return list.replaceChildren(h('p', { class: 'muted' }, items.length ? t('sessions.noMatch') : t('sessions.empty')));
    const out = [];
    let group = null;
    for (const s of shown) {
      const g = dayGroup(s.updated_at);
      if (g !== group) { group = g; out.push(h('div', { class: 'sb-group', 'aria-hidden': 'true' }, g)); }
      out.push(row(s));
    }
    list.replaceChildren(...out);
    list.setAttribute('role', 'list');
    rover.refresh();
  }

  function paintNav() {
    const caps = store.get().capabilities, cur = router.current?.name;
    navLinks.replaceChildren(...ROUTES.filter((r) => !r.ui || new URLSearchParams(location.search).has('keynote')).map((r) => {
      const live = r.live || r.ui || caps[r.cap];
      return h('a', { href: hrefFor(r.name), 'aria-current': r.name === cur ? 'page' : null }, icon(r.icon, { size: 16 }), t(`nav.${r.name}`),
        live ? null : chip(`${t('common.planned')} ${r.tasks[0]}`, { outline: true }));
    }));
  }

  store.subscribe(paint, ['sessions', 'session', 'personas']);
  store.subscribe(paintNav, ['capabilities']);
  document.addEventListener('sensai:route', paintNav);
  /** Static labels are set once at creation; repaint them when the language changes. */
  document.addEventListener('sensai:lang', () => {
    newBtn.querySelector('.btn__label').textContent = t('chat.new');
    search.input.placeholder = t('sessions.search'); search.input.setAttribute('aria-label', t('sessions.search'));
    search.querySelector('.search__clear')?.setAttribute('aria-label', t('common.clear'));
    root.setAttribute('aria-label', t('sessions.title')); navLinks.setAttribute('aria-label', t('nav.views'));
    foot.querySelector('summary').replaceChildren(icon('grid', { size: 16 }), t('nav.views'));
    foot.querySelector(':scope > span').textContent = t('everything.local');
    paint(); paintNav();
  });
  paint(); paintNav();
  return root;
}
