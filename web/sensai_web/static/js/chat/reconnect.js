// Reconnect banner with exponential backoff (1, 2, 4, 8 s, max 15 s) after a lost stream (spec 6.12).
import { h } from '../dom.js';
import { banner } from '../components/banners.js';
import { toast } from '../components/toast.js';
import { t } from '../i18n.js';

export function createReconnect({ api, actions, onRestored }) {
  const box = h('div', { class: 'reconnect' });
  let timer, left = 0, delay = 1000, running = false;

  function paint() {
    box.replaceChildren(banner({ tone: 'error', inline: true, text: t('reconnect.text', { s: left }), actions: [{ label: t('banner.reconnect'), onClick: attempt }] }));
  }
  async function attempt() {
    clearInterval(timer);
    box.firstChild?.setAttribute('aria-busy', 'true');
    try {
      await api.health();
      running = false; delay = 1000; box.replaceChildren();
      actions.setStatus({ backend: 'ok', retryIn: null });
      await onRestored();
      toast(t('reconnect.done'));
    } catch {
      left = Math.round(delay / 1000); delay = Math.min(delay * 2, 15000);
      paint(); timer = setInterval(() => { left -= 1; if (left <= 0) attempt(); else paint(); }, 1000);
    }
  }
  return {
    el: box,
    start() { if (running) return; running = true; delay = 1000; left = 1; paint(); timer = setInterval(() => { left -= 1; if (left <= 0) attempt(); }, 1000); },
    now() { running = true; return attempt(); },
    dispose() { clearInterval(timer); running = false; },
  };
}
