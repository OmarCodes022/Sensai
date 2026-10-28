// Tiny observable store. set(patch) merges and notifies subscribers with changed keys.
export function createStore(initial) {
  let state = { ...initial };
  const subs = new Set();
  return {
    get: () => state,
    set(patch) {
      const changed = Object.keys(patch).filter((k) => state[k] !== patch[k]);
      if (!changed.length) return;
      state = { ...state, ...patch };
      for (const s of [...subs]) if (!s.keys || changed.some((k) => s.keys.includes(k))) s.fn(state, changed);
    },
    /** subscribe(fn, ['session']) runs fn(state, changedKeys); returns unsubscribe. */
    subscribe(fn, keys) {
      const s = { fn, keys };
      subs.add(s);
      return () => subs.delete(s);
    },
  };
}

export const initialState = () => ({
  config: null,
  capabilities: {},
  personas: [],
  personasSource: 'builtin',
  activePersona: null,
  session: null,
  sessions: { items: [], state: 'idle' }, // state: idle | loading | error
  prefs: null,
  status: { backend: 'checking', mock: false, streaming: false, locked: false, health: null },
  selectedTurn: null,
});
