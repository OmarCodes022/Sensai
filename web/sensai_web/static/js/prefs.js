// UI preferences only. Never message content. Every storage access is guarded.
export const KEY = 'sensai.prefs';
export const DEFAULTS = {
  theme: 'system', density: 'comfortable', fontSize: 'default', motion: 'system', lang: 'en',
  sidebar: 'open', inspector: 'closed', showTokens: true, showTools: true, showNumbers: true,
  draftLabel: true, showToolJson: false, lastView: 'chat',
};

export function loadPrefs() {
  try { return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(KEY) || '{}') }; }
  catch { return { ...DEFAULTS }; }
}

export function savePrefs(prefs) {
  try { localStorage.setItem(KEY, JSON.stringify(prefs)); } catch { /* storage unavailable */ }
}

export function resetPrefs() {
  try { localStorage.removeItem(KEY); } catch { /* storage unavailable */ }
  return { ...DEFAULTS };
}

/** Mirrors prefs onto <html> data attributes (CSS does the rest). */
export function applyPrefs(p) {
  const r = document.documentElement;
  const set = (name, on, val) => (on ? r.setAttribute(name, val) : r.removeAttribute(name));
  set('data-theme', p.theme !== 'system', p.theme);
  set('data-density', p.density !== 'comfortable', p.density);
  set('data-font', p.fontSize !== 'default', p.fontSize);
  set('data-motion', p.motion === 'reduce', 'reduce');
}
