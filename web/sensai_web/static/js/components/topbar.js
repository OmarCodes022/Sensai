import { h } from '../dom.js';
import { icon, seal } from '../icons.js';
import { iconButton } from './button.js';
import { chip, statusDot } from './chip.js';
import { openPopover } from './popover.js';
import { ollamaState, ollamaPanel, modelPanel, allPanel } from './status.js';
import { kbd } from './meter.js';
import { modKey } from '../platform.js';
import { stripInvisible } from '../safetext.js';
import { t } from '../i18n.js';

const THEME_ICON = { system: 'sliders', light: 'sun', dark: 'moon' };
const NEXT = { system: 'light', light: 'dark', dark: 'system' };
export const personaTone = (i) => ['accent', 'teal', 'plum', 'sage', 'amber'][i % 5];

function personaPopover(anchor, { store }, actions) {
  const { personas, activePersona } = store.get();
  const list = h('div', { role: 'listbox', 'aria-label': t('persona.switcher') });
  let typed = '', timer;
  const opts = personas.map((p, i) => {
    const o = h('button', { type: 'button', class: 'menu-item persona-opt', role: 'option', 'aria-selected': String(p.id === activePersona), tabindex: p.id === activePersona || (!activePersona && !i) ? '0' : '-1', dataset: { id: p.id } },
      h('span', { class: 'row' }, h('strong', null, p.name), h('code', { class: 'chip chip--mono' }, p.id), p.id === activePersona ? icon('check', { size: 16 }) : null),
      h('span', { class: 'muted' }, p.role), p.tone ? h('span', { class: 'muted' }, `${t('persona.tone')}: ${p.tone}`) : null);
    return o;
  });
  list.append(...opts);
  const pop = openPopover(anchor, [list, h('a', { href: '#/personas', class: 'btn btn--ghost btn--sm', onclick: () => pop.close() }, t('persona.details'))], { menu: false, label: t('persona.switcher') });
  list.addEventListener('click', (e) => { const b = e.target.closest('[role=option]'); if (b) { pop.close(); actions.setPersona(b.dataset.id); anchor.focus(); } });
  list.addEventListener('keydown', (e) => {
    const i = opts.indexOf(document.activeElement);
    let to;
    if (e.key === 'ArrowDown') to = opts[(i + 1) % opts.length];
    else if (e.key === 'ArrowUp') to = opts[(i - 1 + opts.length) % opts.length];
    else if (e.key === 'Home') to = opts[0];
    else if (e.key === 'End') to = opts[opts.length - 1];
    else if (e.key.length === 1) { typed += e.key.toLowerCase(); clearTimeout(timer); timer = setTimeout(() => { typed = ''; }, 600); to = opts.find((o, k) => personas[k].name.toLowerCase().startsWith(typed)); }
    if (to) { e.preventDefault(); opts.forEach((o) => { o.tabIndex = o === to ? 0 : -1; }); to.focus(); }
  });
  return pop;
}

export function createTopbar({ store, actions, layout, openPalette, openShortcuts }) {
  const sbBtn = iconButton('panel-left', t('topbar.toggleSidebar'), { 'aria-expanded': 'true', onClick: layout.toggleSidebar });
  const inBtn = iconButton('panel-right', t('topbar.toggleInspector'), { 'aria-expanded': 'false', onClick: layout.toggleInspector });
  const themeBtn = iconButton('sliders', '', { onClick: actions.cycleTheme });
  const title = h('span', { class: 'session-meta__title truncate' });
  const idBtn = h('button', { type: 'button', 'data-tip': t('session.copyId'), onclick: actions.copySessionId });
  const saved = h('span');
  const dot = h('button', { type: 'button', class: 'btn btn--pill btn--sm', 'aria-haspopup': 'dialog', 'aria-expanded': 'false' });
  dot.addEventListener('click', () => openPopover(dot, ollamaPanel(store.get().status), { label: t('status.ollama') }));
  const model = h('button', { type: 'button', class: 'btn btn--sm mono', 'aria-haspopup': 'dialog', 'aria-expanded': 'false' });
  model.addEventListener('click', () => openPopover(model, modelPanel(store.get().status), { label: t('status.model') }));
  const remote = h('span', { hidden: true }, chip(t('status.remoteShort'), { tone: 'teal', icon: 'link' }));
  const personaBtn = h('button', { type: 'button', class: 'persona-pill', 'aria-haspopup': 'listbox', 'aria-expanded': 'false' });
  personaBtn.addEventListener('click', () => personaPopover(personaBtn, { store }, actions));
  const creator = h('span', { class: 'chip chip--outline hide-mid hide-1400', tabindex: '0', 'data-tip': t('creator.tip') });
  const statusBtn = h('button', { type: 'button', class: 'btn btn--sm status-btn', 'aria-haspopup': 'dialog', 'aria-expanded': 'false' }, icon('info', { size: 16 }), h('span', { class: 'status-btn__label' }, t('status.button')));
  // At narrow widths the session title and saved state are hidden from the bar, so the status panel carries them.
  const sessionSummary = () => {
    const sess = store.get().session;
    return h('div', { class: 'stack session-summary' }, h('strong', { dir: 'auto' }, sess?.title ? stripInvisible(sess.title) : t('session.new')),
      h('span', { class: 'mono muted' }, sess ? t('session.id', { id: sess.id }) : ''), h('span', { class: 'muted' }, sess?.saved ? t('session.saved') : t('session.notSaved')));
  };
  statusBtn.addEventListener('click', () => openPopover(statusBtn, [sessionSummary(), allPanel(store.get().status)], { label: t('status.button') }));
  const mock = h('span', { class: 'hide-narrow', hidden: true }, chip(t('common.mockData'), { tone: 'amber' }));
  const paletteBtn = h('button', { type: 'button', class: 'btn hide-mid', onclick: openPalette }, t('topbar.search'), ...kbd(`${modKey()} K`));
  const helpBtn = iconButton('keyboard', t('shortcuts.title'), { onClick: openShortcuts });
  helpBtn.classList.add('hide-narrow');

  const header = h('header', { class: 'topbar' },
    sbBtn,
    h('a', { class: 'brand', href: '#/chat', 'aria-label': 'Sensai' }, seal(), h('span', null, 'Sensai')),
    h('span', { class: 'topbar__sep hide-narrow' }),
    h('div', { class: 'session-meta grow hide-narrow' }, title, h('span', { class: 'session-meta__sub' }, idBtn, saved)),
    mock,
    h('div', { class: 'status-cluster' }, dot, model, remote), statusBtn, personaBtn, creator, paletteBtn, themeBtn, helpBtn, inBtn);

  function paint() {
    const s = store.get(), sess = s.session, prefs = s.prefs;
    const os = ollamaState(s.status);
    dot.replaceChildren(statusDot(os.tone), os.text);
    model.textContent = s.status.health?.model?.name || s.config?.model || t('common.na');
    remote.hidden = !s.status.health?.remote;
    mock.hidden = !s.status.mock;
    const tt = sess?.title ? stripInvisible(sess.title) : t('session.new');
    title.textContent = tt;
    idBtn.textContent = sess ? t('session.id', { id: sess.id }) : '';
    saved.className = `saved ${sess?.saved ? '' : 'saved--no'}`;
    saved.title = sess?.saved ? '' : t('session.savedAfter');
    saved.replaceChildren(icon(sess?.saved ? 'check' : 'clock', { size: 12 }), sess?.saved ? t('session.saved') : t('session.notSaved'));
    const active = s.personas.find((p) => p.id === s.activePersona);
    const idx = Math.max(0, s.personas.findIndex((p) => p.id === s.activePersona));
    personaBtn.replaceChildren(h('span', { class: 'avatar', dataset: { tone: personaTone(idx) }, 'aria-hidden': 'true' }, (active?.name || '?')[0].toUpperCase()), h('span', { class: 'persona-pill__name' }, active?.name || t('persona.none')), icon('chevron-down', { size: 16 }));
    personaBtn.setAttribute('aria-label', `${t('persona.switcher')}: ${active?.name || t('persona.none')}`);
    personaBtn.disabled = s.status.streaming;
    personaBtn.dataset.tip = s.status.streaming ? t('persona.waitTip') : '';
    creator.replaceChildren(icon('user', { size: 12 }), t('creator.chip', { key: s.config?.creator || sess?.creator || 'default' }));
    themeBtn.replaceChildren(icon(THEME_ICON[prefs.theme], { size: 18 }));
    const label = t('topbar.themeNext', { theme: t(`theme.${NEXT[prefs.theme]}`) });
    themeBtn.setAttribute('aria-label', label); themeBtn.dataset.tip = label;
  }
  layout.onChange((st) => { sbBtn.setAttribute('aria-expanded', String(st.sb === 'open')); inBtn.setAttribute('aria-expanded', String(st.inn === 'open')); });
  store.subscribe(paint, ['session', 'personas', 'activePersona', 'status', 'config', 'prefs']);
  const tip = (b, text) => { b.setAttribute('aria-label', text); b.dataset.tip = text; };
  /** Static labels are set once at creation; repaint them when the language changes. */
  const relabel = () => {
    tip(sbBtn, t('topbar.toggleSidebar')); tip(inBtn, t('topbar.toggleInspector')); tip(helpBtn, t('shortcuts.title'));
    idBtn.dataset.tip = t('session.copyId'); creator.dataset.tip = t('creator.tip'); header.querySelector('.brand')?.setAttribute('aria-label', 'Sensai');
    statusBtn.querySelector('.status-btn__label').textContent = t('status.button');
    paletteBtn.replaceChildren(t('topbar.search'), ...kbd(`${modKey()} K`));
    mock.replaceChildren(chip(t('common.mockData'), { tone: 'amber' })); remote.replaceChildren(chip(t('status.remoteShort'), { tone: 'teal', icon: 'link' }));
    paint();
  };
  document.addEventListener('sensai:lang', relabel);
  paint();
  return header;
}
