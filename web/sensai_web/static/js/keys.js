// Global keyboard shortcuts (spec 8.7). Chat-specific keys (Enter, Esc, Up, y/n/v) live in the chat view.
import { hasMod } from './platform.js';
import { ROUTES, hrefFor } from './router.js';

const typing = (e) => e.target.matches?.('input, textarea, select, [contenteditable]');

export function installKeys({ actions, layout, router, openPalette, openShortcuts }) {
  const views = ROUTES.filter((r) => r.key);
  document.addEventListener('keydown', (e) => {
    if (document.querySelector('dialog[open]') && !(hasMod(e) && e.key.toLowerCase() === 'k')) return;
    const k = e.key.toLowerCase();
    if (hasMod(e) && !e.altKey) {
      if (k === 'k') { e.preventDefault(); if (!document.querySelector('dialog.palette[open]')) openPalette(); }
      else if (k === 'o' && e.shiftKey) { e.preventDefault(); actions.newChat(); }
      else if (k === 'l' && e.shiftKey) { e.preventDefault(); actions.cycleTheme(); }
      else if (k === 'b' && !e.shiftKey) { e.preventDefault(); layout.toggleSidebar(); }
      else if (k === '.') { e.preventDefault(); layout.toggleInspector(); }
      else if (k === '/') { e.preventDefault(); openShortcuts(); }
    } else if (e.altKey && /^[1-6]$/.test(e.key)) {
      e.preventDefault();
      router.go(hrefFor(views[Number(e.key) - 1].name));
    } else if (k === '?' && !typing(e)) { e.preventDefault(); openShortcuts(); }
    else if (e.key === 'Escape' && layout.closeOverlays()) e.preventDefault();
  });
}
