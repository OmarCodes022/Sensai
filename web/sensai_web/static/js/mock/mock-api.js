// Mock backend with the same interface as api.js: latency, token streaming, error injection.
import { ApiError } from '../errors.js';
import { createSessions } from './session-store.js';
import { play, abortError } from './player.js';
import { SCENARIOS, byId, errorTurn } from './scenarios.js';
import { turn, say, usage } from './script.js';
import { PERSONAS, HEALTH, CONFIG, PROFILE, TOOLS, DATA_FILES, ENGAGEMENT_CSV } from './fixtures.js';
import { DOCS, CHUNKS } from './planned-misc.js';

const state = { scenario: 'happy', turnIdx: 0, speed: 'normal', inject: null, locked: false, offline: false, hideSessions: false, noTools: false };
const sessions = createSessions();
let dataFolder = structuredClone(DATA_FILES);
const docItem = (d) => ({ name: `${d.id}.md`, bytes: d.chunks * 420, state: 'ready', source: d.id, version: d.version, title: d.product, product: d.type === 'Product sheet' ? d.product : '', chunks: d.chunks });
let docFiles = DOCS.map(docItem);
const docListing = () => ({ state: 'ready', folder: '/Users/nadia/sensai/data/docs', embed_model: 'nomic-embed-text', documents: docFiles.length, pending: 0, error: null,
  items: structuredClone(docFiles), limits: { file_mb: 2, total_mb: 20, types: ['.md', '.txt'] } });
const wordsOf = (s) => s.toLowerCase().match(/[\p{L}\p{N}]+/gu) || [];
const pending = new Map();
let active = null, profile = { ...PROFILE, preferences: { ...PROFILE.preferences } }, turnCount = 0, panelReady = false;
const listeners = new Set();
const notify = () => listeners.forEach((f) => f(state));
const lat = (ms = 50) => new Promise((r) => setTimeout(r, state.speed === 'instant' ? 0 : ms + Math.random() * 70));
const personaName = (id) => PERSONAS.find((p) => p.id === id)?.name || id;

const generic = (text) => turn(null, [say(`This is a mock reply to: "${text.slice(0, 60)}". Pick a scenario in the dev panel (Ctrl+Shift+D).`), usage(null, null, 1200, null)]);

/** Dev panel hooks. */
export const control = {
  state, scenarios: SCENARIOS, sessions, onChange: (f) => { listeners.add(f); return () => listeners.delete(f); },
  select(id) {
    const sc = byId(id);
    Object.assign(state, { scenario: sc.id, turnIdx: 0, locked: false, offline: false, hideSessions: false, noTools: false, inject: null });
    sessions.fresh(sc.persona || sessions.current().persona);
    sc.setup?.({ sessions, state, persona: () => sc.persona || 'redaction' });
    notify();
    return sc;
  },
  reset() { Object.assign(state, { turnIdx: 0, inject: null, locked: false, offline: false, hideSessions: false, noTools: false }); sessions.reset(); notify(); },
  set(patch) { Object.assign(state, patch); notify(); },
};

function ready() {
  if (panelReady) return;
  panelReady = true;
  import('./devpanel.js').then((m) => m.installDevPanel(control)).catch(() => {});
}
const guard = (fn) => async (...a) => {
  ready();
  if (state.offline) { await lat(); throw new ApiError('network', 'The page cannot reach the Sensai backend.'); }
  if (state.locked) { await lat(); throw new ApiError('tab_locked', 'Sensai is open in another tab.', { status: 409 }); }
  await lat();
  return fn(...a);
};

async function chat(text, { onEvent, signal } = {}) {
  const s = sessions.current();
  const sc = byId(state.scenario);
  let script;
  if (state.inject) { script = errorTurn(state.inject, s.persona); state.inject = null; }
  else { const t = sc.turns[state.turnIdx++]; script = t ? (typeof t === 'function' ? t(text) : t) : generic(text); }
  notify();
  const ctx = { sid: s.id, persona: s.persona, number: s.usage.turns + 1, turnId: `t_${++turnCount}`, saved: s.saved, skipSave: false };
  const played = [];
  active = new AbortController();
  const stop = () => active.abort();
  signal?.addEventListener('abort', stop, { once: true });
  const sig = active.signal;
  try {
    const status = await play(script, { ctx, speed: state.speed, signal: sig, onEvent: (ev) => { played.push(ev); onEvent?.(ev); },
      awaitApproval: (id, sg) => new Promise((resolve, reject) => { pending.set(id, resolve); sg.addEventListener('abort', () => { pending.delete(id); reject(abortError()); }, { once: true }); }) });
    if (status === 'completed' && !ctx.skipSave) sessions.commit(text, played);
    else if (status === 'completed') s.usage = { ...s.usage, turns: s.usage.turns + 1 };
  } catch (e) {
    if (e.code === 'network') { state.offline = true; notify(); setTimeout(() => { state.offline = false; notify(); }, 4500); }
    throw e;
  } finally { active = null; }
}

const impl = {
  health: async () => ({ ...HEALTH }),
  config: async () => ({ ...CONFIG }),
  personas: async () => ({ active: sessions.current().persona, source: 'builtin', items: PERSONAS }),
  async setPersona(id) {
    if (!PERSONAS.some((p) => p.id === id)) throw new ApiError('persona_unknown', `unknown persona: ${id}`, { status: 404 });
    sessions.current().persona = id;
    sessions.addEvent(`Persona changed to ${personaName(id)}`);
    return { active: id };
  },
  async savePersona(id, data) {
    const i = PERSONAS.findIndex((p) => p.id === id);
    const entry = { ...(PERSONAS[i] || {}), id, name: data.name, tone: data.tone, role: data.role, response_scope: data.response_scope };
    if (i < 0) PERSONAS.push(entry); else PERSONAS[i] = entry;
    return { result: i < 0 ? 'added' : 'updated', active: sessions.current().persona, items: PERSONAS.map((p) => ({ ...p })) };
  },
  async deletePersona(id) {
    const i = PERSONAS.findIndex((p) => p.id === id);
    if (i < 0) throw new ApiError('persona_unknown', `unknown persona: ${id}`, { status: 404 });
    if (PERSONAS.length === 1) throw new ApiError('bad_persona', 'Keep at least one persona.', { status: 400 });
    PERSONAS.splice(i, 1);
    if (sessions.current().persona === id) sessions.current().persona = PERSONAS[0].id;
    return { active: sessions.current().persona, items: PERSONAS.map((p) => ({ ...p })) };
  },
  session: async () => sessions.snapshot(),
  newSession: async () => sessions.snapshot(sessions.fresh()),
  sessions: async () => ({ items: state.hideSessions ? [] : sessions.list() }),
  async getSession(id) { const s = sessions.get(id); if (!s) throw new ApiError('not_found', `unknown session: ${id}`, { status: 404 }); return sessions.snapshot(s); },
  async resume(id) { if (!sessions.get(id)) throw new ApiError('not_found', `unknown session: ${id}`, { status: 404 }); return sessions.snapshot(sessions.setCurrent(id)); },
  async renameSession(id, title) {
    if (!sessions.rename(id, title)) throw new ApiError('not_found', `unknown session: ${id}`, { status: 404 });
    return { title };
  },
  async deleteSession(id) {
    if (id === sessions.current().id) throw new ApiError('session_open', 'Open another conversation (or start a new one) before deleting this one.', { status: 409 });
    if (!sessions.remove(id)) throw new ApiError('not_found', `unknown session: ${id}`, { status: 404 });
    return { items: sessions.list() };
  },
  async exportSession(id) {
    const s = sessions.get(id);
    if (!s) throw new ApiError('not_found', `unknown session: ${id}`, { status: 404 });
    const body = s.items.filter((i) => i.kind === 'user' || i.kind === 'assistant').map((i) => `**${i.kind === 'user' ? 'You' : 'Sensai'}**\n\n${i.text}\n`);
    return { filename: `sensai-${id}.md`, markdown: `# ${s.title}\n\n${body.join('\n')}` };
  },
  async readData(name) {
    const f = dataFolder.files.find((x) => x.name === name);
    if (!f) throw new ApiError('not_found', `No data file named ${name}.`, { status: 404 });
    return { name, bytes: f.bytes, text: name === 'engagement.csv' ? ENGAGEMENT_CSV : '' };
  },
  history: async () => ({ items: sessions.history() }),
  chat,
  async approve(id, approved) { const r = pending.get(id); if (!r) throw new ApiError('not_found', 'no pending approval', { status: 404 }); pending.delete(id); r(!!approved); return { ok: true }; },
  async stopChat() { active?.abort(); return { stopped: true }; },
  tools: async () => ({ items: state.noTools ? [] : TOOLS }),
  async run(code) {
    const loop = /while\s+True/.test(code);
    return { exit_code: loop ? -9 : 0, duration_s: loop ? 15 : 0.3, timed_out: loop, truncated: false, stdout: loop ? '' : '1021.4\n', stderr: '', report: loop ? 'Time limit reached (15 s)' : 'Exit code 0 · 0.3 s' };
  },
  runData: async () => structuredClone(dataFolder),
  async putData(name, text) {
    if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$/.test(name)) throw new ApiError('bad_file_name', 'Use letters, digits, dots, dashes and underscores (no folders).', { status: 400 });
    if (!dataFolder.limits.types.some((x) => name.toLowerCase().endsWith(x))) throw new ApiError('bad_file_type', `Only ${dataFolder.limits.types.join(', ')} files can be added.`, { status: 400 });
    const bytes = new TextEncoder().encode(text).length;
    dataFolder.files = [...dataFolder.files.filter((f) => f.name !== name), { name, bytes }].sort((a, b) => a.name.localeCompare(b.name));
    dataFolder.exists = true;
    return structuredClone(dataFolder);
  },
  async deleteData(name) {
    if (!dataFolder.files.some((f) => f.name === name)) throw new ApiError('not_found', `No data file named ${name}.`, { status: 404 });
    dataFolder.files = dataFolder.files.filter((f) => f.name !== name);
    return structuredClone(dataFolder);
  },
  docs: async () => docListing(),
  async putDoc(name, text) {
    if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$/.test(name) || !/\.(md|txt)$/i.test(name)) throw new ApiError('bad_document', 'Only .md and .txt documents can be added (letters, digits, dots, dashes, underscores).', { status: 400 });
    docFiles = [...docFiles.filter((d) => d.name !== name), { name, bytes: new TextEncoder().encode(text).length, state: 'ready', source: name.replace(/\.[^.]+$/, ''), version: '2026-10-26', title: name, product: '', chunks: Math.max(1, text.split(/\n\n+/).length) }].sort((a, b) => a.name.localeCompare(b.name));
    return docListing();
  },
  async deleteDoc(name) {
    if (!docFiles.some((d) => d.name === name)) throw new ApiError('bad_document', `No document named ${name}.`, { status: 404 });
    docFiles = docFiles.filter((d) => d.name !== name);
    return docListing();
  },
  async docView(name) {
    const d = docFiles.find((x) => x.name === name);
    if (!d) throw new ApiError('bad_document', `No document named ${name}.`, { status: 404 });
    const text = `---\nsource: ${d.source}\nversion: ${d.version}\n---\n\n# ${d.title}\n\n${CHUNKS.filter((c) => c.source === d.source).map((c) => c.text).join('\n\n') || 'Sample document (mock).'}\n`;
    return { name, bytes: text.length, text, source: d.source, version: d.version, product: d.product, title: d.title, chunks: d.chunks };
  },
  reindexDocs: async () => docListing(),
  async searchDocs(q) {
    const qs = new Set(wordsOf(q));
    const items = CHUNKS.map((c) => ({ source: c.source, score: qs.size ? wordsOf(c.text).filter((w) => qs.has(w)).length / qs.size : 0, text: c.text })).filter((c) => c.score > 0).sort((a, b) => b.score - a.score).slice(0, 3);
    return { items, state: 'ready' };
  },
  async exampleData() {
    if (dataFolder.files.some((f) => f.name === 'engagement.csv')) throw new ApiError('exists', 'engagement.csv is already in the data folder.', { status: 409 });
    return impl.putData('engagement.csv', ENGAGEMENT_CSV);
  },
  profile: async () => ({ ...profile }),
  async putProfile(preferences) { profile = { ...profile, preferences: { ...preferences } }; return { ...profile }; },
  async takeover() { state.locked = false; notify(); return { ok: true }; },
};

export const mockApi = Object.fromEntries(Object.entries(impl).map(([k, fn]) => [k, k === 'takeover' || k === 'stopChat' ? fn : guard(fn)]));
