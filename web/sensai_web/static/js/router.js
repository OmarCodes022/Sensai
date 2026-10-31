// Hash router. Routes come from spec 4.2 (roadmap was removed). Planned routes render the Planned view.
import { clear } from './dom.js';
import { emptyState } from './components/state.js';
import { t } from './i18n.js';

/** live: wired today. cap: capability flag that turns a planned surface live. tasks: owning task IDs. */
export const ROUTES = [
  { name: 'chat', icon: 'chat', live: true, key: 1 },
  { name: 'sessions', icon: 'history', live: true, key: 2 },
  { name: 'personas', icon: 'persona', live: true, key: 3 },
  { name: 'profile', icon: 'user', live: true, key: 4 },
  { name: 'tools', icon: 'tools', live: true, key: 5 },
  { name: 'settings', icon: 'settings', live: true, key: 6 },
  { name: 'campaign', icon: 'calendar', cap: 'campaign', tasks: ['T40', 'T45', 'T46', 'T50', 'T53'] },
  { name: 'brand', icon: 'star', cap: 'facts', tasks: ['T32', 'T07'] },
  { name: 'documents', icon: 'folder', cap: 'documents', tasks: ['T35', 'T36', 'T43'] },
  { name: 'insights', icon: 'chart', cap: 'stats', tasks: ['T33'] },
  { name: 'safety', icon: 'shield-check', cap: 'evaluation', tasks: ['T47', 'T10'] },  // Guardrails (T38) work in chat; this page comes with EV1.
  { name: 'schedule', icon: 'clock', cap: 'schedule', tasks: ['T51'] },
  { name: 'keynote', icon: 'play', ui: true },
];

export function parseHash(hash = location.hash) {
  const [name = 'chat', ...rest] = hash.replace(/^#\/?/, '').split('/').filter(Boolean);
  let id = null;
  try { id = rest[0] ? decodeURIComponent(rest[0]) : null; } catch { return { name: null, route: undefined, params: { id: null }, raw: hash }; }
  const route = ROUTES.find((r) => r.name === (name || 'chat'));
  return { name: route ? route.name : null, route, params: { id }, raw: hash };
}

export const hrefFor = (name, id) => `#/${name}${id ? `/${encodeURIComponent(id)}` : ''}`;

export function createRouter(ctxFactory, root, caps) {
  let current = null, unmount = null, seq = 0;
  const router = {
    get current() { return current; },
    go(path) { if (location.hash === path) render(); else location.hash = path; },
    // A language change repaints the whole page, not just the shell. The chat repaints itself (and waits for a reply in progress).
    start() { addEventListener('hashchange', render); document.addEventListener('sensai:lang', () => { if (current?.name !== 'chat') render(); }); render(); },
    refresh: render,
  };

  async function load(match) {
    const { route } = match;
    if (!route) return import('./views/notfound.js');
    const live = route.live || route.ui || (route.cap && caps()[route.cap]);
    if (!live) return import('./views/planned.js');
    return import(`./views/${route.name}.js`).catch(() => ({ mount: missing }));
  }

  function missing(el) {
    el.append(emptyState({ icon: 'tools', title: t('router.notBuilt.title'), body: t('router.notBuilt.body') }));
  }

  async function render() {
    const mine = ++seq;
    const match = parseHash();
    if (location.hash === '' ) { history.replaceState(null, '', '#/chat'); }
    unmount?.();
    unmount = null;
    clear(root);
    current = match;
    const mod = await load(match);
    if (mine !== seq) return;
    const ctx = ctxFactory(match);
    unmount = mod.mount(root, ctx) || null;
    document.dispatchEvent(new CustomEvent('sensai:route', { detail: match }));
    if (!match.route || match.name !== 'chat') root.focus({ preventScroll: true });
  }
  return router;
}
