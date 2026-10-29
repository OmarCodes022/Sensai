// Health polling with exponential backoff (1, 2, 4, 8 s, max 15 s) after a failure.
import { api } from './api.js';

export function createConnection(store, actions) {
  let timer, delay = 1000, stopped = false;
  const ok = (health) => { delay = 1000; actions.setStatus({ backend: 'ok', health, retryIn: null }); schedule(30000); };

  async function check() {
    if (api.mode === 'mock' || stopped) return;
    try { ok(await api.health()); }
    catch (e) {
      if (e.status === 409) return schedule(30000);
      actions.setStatus({ backend: 'offline', retryIn: Math.round(delay / 1000) });
      schedule(delay);
      delay = Math.min(delay * 2, 15000);
    }
  }
  function schedule(ms) { clearTimeout(timer); timer = setTimeout(check, ms); }
  return { start: () => schedule(30000), check, ok };
}
