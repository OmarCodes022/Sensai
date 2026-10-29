import { h, nextId } from '../dom.js';
import { openModal } from './modal.js';
import { chip } from './chip.js';
import { ROUTES, hrefFor } from '../router.js';
import { t } from '../i18n.js';

/** Subsequence fuzzy score; higher is better, -1 means no match. */
export function fuzzy(q, text) {
  q = q.toLowerCase(); text = text.toLowerCase();
  if (!q) return 0;
  let i = 0, score = 0, prev = -2;
  for (let k = 0; k < text.length && i < q.length; k++) {
    if (text[k] === q[i]) { score += prev === k - 1 ? 3 : 1; if (k === 0 || text[k - 1] === ' ') score += 2; prev = k; i++; }
  }
  return i === q.length ? score : -1;
}

export function openPalette({ store, actions, router, layout, openShortcuts }) {
  const s = store.get();
  const items = [
    ...s.sessions.items.map((x) => ({ g: 'sessions', label: x.title || t('sessions.untitled'), sub: x.id, run: () => router.go(hrefFor('chat', x.id)) })),
    ...s.personas.map((p) => ({ g: 'personas', label: p.name, sub: p.id, run: () => actions.setPersona(p.id) })),
    ...ROUTES.filter((r) => r.live || r.ui || s.capabilities[r.cap]).map((r) => ({ g: 'views', label: t(`nav.${r.name}`), run: () => router.go(hrefFor(r.name)) })),
    { g: 'commands', label: t('cmd.newChat'), run: actions.newChat }, { g: 'commands', label: t('cmd.theme'), run: actions.cycleTheme },
    { g: 'commands', label: t('cmd.sidebar'), run: layout.toggleSidebar }, { g: 'commands', label: t('cmd.shortcuts'), run: openShortcuts },
    { g: 'commands', label: t('cmd.copyId'), run: actions.copySessionId },
    ...ROUTES.filter((r) => !(r.live || r.ui || s.capabilities[r.cap])).map((r) => ({ g: 'planned', label: t(`nav.${r.name}`), sub: r.tasks.join(' '), disabled: true })),
  ];
  const id = nextId('pal');
  const input = h('input', { class: 'input', role: 'combobox', 'aria-label': t('palette.title'), 'aria-expanded': 'true', 'aria-controls': `${id}-lb`, 'aria-autocomplete': 'list', placeholder: t('palette.placeholder'), autocomplete: 'off' });
  const list = h('div', { class: 'palette-list', role: 'listbox', id: `${id}-lb`, 'aria-label': t('palette.title') });
  let shown = [], active = 0;

  const paint = () => {
    const out = [];
    let g = null;
    shown.forEach((it, i) => {
      if (it.g !== g) { g = it.g; out.push(h('div', { class: 'palette-group', role: 'presentation' }, t(`palette.${g}`))); }
      out.push(h('div', { class: 'option', role: 'option', id: `${id}-${i}`, 'aria-selected': String(i === active), 'data-active': String(i === active), 'aria-disabled': it.disabled ? 'true' : null },
        h('span', { class: 'grow truncate' }, it.label), it.sub ? h('span', { class: 'muted mono' }, it.sub) : null, it.disabled ? chip(t('common.planned'), { outline: true }) : null));
    });
    list.replaceChildren(...(out.length ? out : [h('p', { class: 'muted', role: 'presentation' }, t('palette.none'))]));
    input.setAttribute('aria-activedescendant', shown.length ? `${id}-${active}` : '');
    list.querySelector('[data-active=true]')?.scrollIntoView({ block: 'nearest' });
  };
  const filter = () => {
    shown = items.map((it) => ({ it, sc: fuzzy(input.value, `${it.label} ${it.sub || ''}`) })).filter((x) => x.sc >= 0).sort((a, b) => b.sc - a.sc).map((x) => x.it);
    const order = ['sessions', 'personas', 'views', 'commands', 'planned'];
    shown.sort((a, b) => order.indexOf(a.g) - order.indexOf(b.g));
    active = 0; paint();
  };
  const m = openModal({ label: t('palette.title'), body: [input, list], top: true, className: 'palette' });
  const pick = (i) => { const it = shown[i]; if (!it || it.disabled) return; m.close(); setTimeout(it.run, 0); };
  input.addEventListener('input', filter);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); active = (active + 1) % Math.max(1, shown.length); paint(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); active = (active - 1 + shown.length) % Math.max(1, shown.length); paint(); }
    else if (e.key === 'Enter') { e.preventDefault(); pick(active); }
  });
  list.addEventListener('click', (e) => { const o = e.target.closest('.option'); if (o) pick([...list.querySelectorAll('.option')].indexOf(o)); });
  filter();
  input.focus();
}
