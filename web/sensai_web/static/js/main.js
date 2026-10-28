// Boot: prefs, language, backend mode, shell, router.
import { h } from './dom.js';
import { chip } from './components/chip.js';
import { createStore, initialState } from './store.js';
import { loadPrefs, applyPrefs } from './prefs.js';
import { setLang, t } from './i18n.js';
import { api } from './api.js';
import { createRouter } from './router.js';
import { createActions } from './actions.js';
import { createLayout } from './layout.js';
import { announce } from './a11y.js';
import { initTooltips } from './components/tooltip.js';
import { createTopbar } from './components/topbar.js';
import { createSidebar } from './components/sidebar.js';
import { createInspector } from './components/inspector.js';
import { createBanners } from './components/banners.js';
import { openPalette } from './components/palette.js';
import { openShortcuts } from './components/shortcuts.js';
import { showLock } from './components/lock.js';
import { confirmDialog } from './components/modal.js';
import { installKeys } from './keys.js';
import { createConnection } from './connection.js';
import { stripInvisible } from './safetext.js';
import { installPrint } from './print.js';

/** Destination shown in full, with the host on its own line; non-ASCII hosts get a warning and the punycode form. */
function linkMessage(url) {
  let host = '', puny = '';
  try { puny = new URL(url).hostname; host = /^[a-z][a-z0-9+.-]*:\/\/(?:[^/?#@]*@)?([^/?#:]+)/i.exec(url)?.[1] || puny; } catch { /* shown as typed */ }
  const odd = /[^\x00-\x7F]/.test(host) || /(^|\.)xn--/i.test(puny);
  return h('div', { class: 'stack' }, h('p', null, t('link.body', { url })), h('p', null, t('link.host'), ' ', h('strong', { class: 'mono' }, host || t('common.na'))),
    odd ? h('p', { class: 'field__error', role: 'alert' }, chip(t('link.idnChip'), { tone: 'rose', icon: 'alert-triangle' }), ' ', t('link.idn', { puny })) : null);
}

async function boot() {
  const prefs = loadPrefs();
  applyPrefs(prefs);
  await setLang(prefs.lang);
  const store = createStore({ ...initialState(), prefs });
  const { mode, fallback } = await api.init();
  store.set({ status: { ...store.get().status, mock: mode === 'mock' } });

  const root = document.getElementById('app');
  const main = h('main', { class: 'main', id: 'main', tabindex: '-1' });
  const app = h('div', { class: 'app' });
  const router = createRouter((match) => ({ store, api, router, t, announce, actions, layout, params: match.params }), main, () => store.get().capabilities);
  const actions = createActions({ store, api, router });
  const layout = createLayout(app, store, actions.setPref);
  const conn = createConnection(store, actions);
  const deps = { store, actions, layout, router, api, openShortcuts, openPalette: () => openPalette({ store, actions, router, layout, openShortcuts }) };

  const banners = createBanners({ store, fallback, onReconnect: conn.check });
  app.append(createTopbar(deps), banners,
    h('div', { class: 'body' }, createSidebar(deps), main, createInspector(deps)),
    h('div', { class: 'scrim', onclick: layout.closeOverlays }));
  root.replaceChildren(app);

  for (const a of document.querySelectorAll('[data-skip]')) {
    a.addEventListener('click', (e) => { e.preventDefault(); (document.getElementById(a.dataset.skip) || main).focus(); });
  }
  initTooltips();
  installPrint();
  installKeys(deps);
  api.onLocked(() => { if (!store.get().status.locked) { actions.setStatus({ locked: true }); showLock(api, actions); } });

  // Links from model text: show the real destination and confirm before opening a new tab.
  document.addEventListener('click', async (e) => {
    const a = e.target.closest?.('a.md-link');
    if (!a) return;
    e.preventDefault();
    if (await confirmDialog({ title: t('link.title'), message: linkMessage(a.dataset.url), confirmLabel: t('link.open') })) window.open(a.dataset.url, '_blank', 'noopener,noreferrer');
  });

  document.addEventListener('sensai:route', () => {
    const s = store.get().session;
    if (router.current?.name === 'chat') document.title = s?.title ? `${stripInvisible(s.title)} - Sensai` : 'Sensai';
  });

  const settle = async (p) => { try { return await p; } catch { return null; } };
  const [health, config, personas, session] = await Promise.all([settle(api.health()), settle(api.config()), settle(api.personas()), settle(api.session())]);
  store.set({
    config, capabilities: config?.capabilities || {}, personas: personas?.items || [], personasSource: personas?.source || 'builtin',
    activePersona: personas?.active ?? session?.persona ?? null, session,
    status: { ...store.get().status, backend: health ? 'ok' : 'offline', health },
  });
  actions.refreshSessions();
  router.start();
  conn.start();
}

boot();
