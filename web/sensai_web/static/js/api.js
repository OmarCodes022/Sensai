// The ONLY module that talks to the backend. One interface, real or mock behind it.
import { streamNdjson } from './stream.js';
import { ApiError, errorFromResponse } from './errors.js';
import { mockApi } from './mock/mock-api.js';

let lockedHandler = () => {};
let mode = 'real';

// One id per browser tab: the backend lets a single tab drive the session at a time (HTTP 409 for the others).
const tabId = (() => {
  const fresh = () => (crypto.randomUUID ? crypto.randomUUID() : String(Math.random()).slice(2));
  try { const id = sessionStorage.getItem('sensai.tab') || fresh(); sessionStorage.setItem('sensai.tab', id); return id; } catch { return fresh(); }
})();
const tabHeader = { 'X-Sensai-Tab': tabId };

async function req(method, path, body) {
  let res;
  try {
    res = await fetch(path, { method, headers: body ? { ...tabHeader, 'Content-Type': 'application/json' } : tabHeader, body: body ? JSON.stringify(body) : undefined });
  } catch { throw new ApiError('network', 'The page cannot reach the Sensai backend.'); }
  if (res.status === 409) lockedHandler();
  if (!res.ok) throw await errorFromResponse(res);
  return res.json();
}

const real = {
  health: () => req('GET', '/api/health'),
  config: () => req('GET', '/api/config'),
  personas: () => req('GET', '/api/personas'),
  setPersona: (id) => req('POST', '/api/persona', { id }),
  savePersona: (id, persona) => req('PUT', `/api/personas/${encodeURIComponent(id)}`, persona),
  deletePersona: (id) => req('DELETE', `/api/personas/${encodeURIComponent(id)}`),
  session: () => req('GET', '/api/session'),
  newSession: () => req('POST', '/api/sessions'),
  sessions: () => req('GET', '/api/sessions'),
  getSession: (id) => req('GET', `/api/sessions/${encodeURIComponent(id)}`),
  resume: (id) => req('POST', `/api/sessions/${encodeURIComponent(id)}/resume`),
  renameSession: (id, title) => req('PATCH', `/api/sessions/${encodeURIComponent(id)}`, { title }),
  deleteSession: (id) => req('DELETE', `/api/sessions/${encodeURIComponent(id)}`),
  exportSession: (id) => req('GET', `/api/sessions/${encodeURIComponent(id)}/export`),
  models: () => req('GET', '/api/models'),
  setModel: (name) => req('POST', '/api/model', { name }),
  history: () => req('GET', '/api/history'),
  async chat(text, { onEvent, signal, think = false } = {}) {
    try { await streamNdjson(think ? '/api/think' : '/api/chat', { body: { text }, signal, onEvent, headers: tabHeader }); }
    catch (e) { if (e.status === 409) lockedHandler(); throw e; }
  },
  stopChat: () => req('POST', '/api/chat/stop'),
  approve: (id, approved) => req('POST', `/api/approvals/${encodeURIComponent(id)}`, { approved }),
  tools: () => req('GET', '/api/tools'),
  reloadTools: () => req('POST', '/api/tools/reload'),
  run: (code) => req('POST', '/api/run', { code }),
  runData: () => req('GET', '/api/run/data'),
  readData: (name) => req('GET', `/api/run/data/${encodeURIComponent(name)}`),
  putData: (name, text) => req('PUT', `/api/run/data/${encodeURIComponent(name)}`, { text }),
  deleteData: (name) => req('DELETE', `/api/run/data/${encodeURIComponent(name)}`),
  exampleData: () => req('POST', '/api/run/data/example'),
  docs: () => req('GET', '/api/docs'),
  docView: (name) => req('GET', `/api/docs/${encodeURIComponent(name)}`),
  putDoc: (name, text) => req('PUT', `/api/docs/${encodeURIComponent(name)}`, { text }),
  deleteDoc: (name) => req('DELETE', `/api/docs/${encodeURIComponent(name)}`),
  reindexDocs: () => req('POST', '/api/docs/reindex'),
  searchDocs: (q) => req('GET', `/api/docs/search?q=${encodeURIComponent(q)}`),
  profile: () => req('GET', '/api/profile'),
  putProfile: (preferences) => req('PUT', '/api/profile', { preferences }),
  takeover: () => req('POST', '/api/session/takeover'),
};

let impl = real;
const wrap = (name) => (...args) => impl[name](...args);
export const api = Object.fromEntries(Object.keys(real).map((n) => [n, wrap(n)]));

Object.defineProperty(api, 'mode', { get: () => mode });
api.onLocked = (fn) => { lockedHandler = fn; };

/** Chooses real or mock. Mock when ?mock=1, or after two failed health calls (fallback = true). */
api.init = async function init() {
  if (new URLSearchParams(location.search).get('mock') === '1') { impl = mockApi; mode = 'mock'; return { mode, fallback: false }; }
  for (let i = 0; i < 2; i++) {
    try { await real.health(); return { mode, fallback: false }; }
    catch (e) { if (e.status === 409) return { mode, fallback: false }; if (i === 0) await new Promise((r) => setTimeout(r, 400)); }
  }
  impl = mockApi; mode = 'mock';
  return { mode, fallback: true };
};
