// In-memory sessions for the mock backend. Items use the same display kinds as GET /api/session.
import { SESSION_META, sampleItems } from './fixtures.js';

const ALPHABET = 'abcdefghjkmnpqrstuvwxyz23456789';
export const newId = () => Array.from({ length: 6 }, () => ALPHABET[Math.floor(Math.random() * ALPHABET.length)]).join('');
const now = () => new Date().toISOString();
const sum = (a, b) => (b == null ? a : (a ?? 0) + b);
const clone = (x) => JSON.parse(JSON.stringify(x));

export function createSessions(persona = 'redaction') {
  const saved = new Map();
  let current;
  const blank = (p) => ({ id: newId(), saved: false, title: null, persona: p, creator: 'default', items: [], usage: { prompt_tokens: null, output_tokens: null, turns: 0 }, created_at: now(), updated_at: now() });
  const seed = () => {
    saved.clear();
    for (const m of SESSION_META) saved.set(m.id, { ...m, saved: true, creator: 'default', items: sampleItems(m), usage: { prompt_tokens: 3200, output_tokens: 940, turns: Math.floor(m.messages / 2) } });
    current = blank(persona);
  };
  seed();

  const api = {
    reset: seed,
    current: () => current,
    fresh(p) { current = blank(p || current.persona); return current; },
    get: (id) => (id === current.id ? current : saved.get(id)),
    setCurrent(id) { current = saved.get(id) || current; return current; },
    list: () => [...saved.values()].map((s) => ({ id: s.id, title: s.title, created_at: s.created_at, updated_at: s.updated_at, persona: s.persona, messages: s.items.filter((i) => i.kind === 'user' || i.kind === 'assistant').length })),
    rename(id, title) { const s = api.get(id); if (!s) return false; s.title = title; return true; },
    remove(id) { return id !== current.id && saved.delete(id); },
    snapshot: (s = current) => clone(s),
    addEvent(text) { current.items.push({ kind: 'event', text }); },
    history: () => current.items.filter((i) => i.kind === 'user').map((i) => {
      const line = i.text.split('\n')[0];
      return { n: i.n, text: line.length > 100 ? `${line.slice(0, 100)} …` : line };
    }),
    /** Folds the stream events of a completed turn into display items and saves the session. */
    commit(text, events) {
      const s = current;
      const at = now();
      const tools = [], a = { kind: 'assistant', text: '', persona: s.persona, usage: null, tools, at };
      for (const ev of events) {
        if (ev.type === 'text') a.text += ev.delta;
        else if (ev.type === 'tool_call') tools.push({ kind: 'tool', id: ev.id, name: ev.name, arguments: ev.arguments, round: ev.round, ok: null });
        else if (ev.type === 'tool_result') Object.assign(tools.find((x) => x.id === ev.id) || {}, { ok: ev.ok, error: ev.error, output: ev.output, duration_ms: ev.duration_ms, meta: ev.meta });
        else if (ev.type === 'approval_result' && !ev.approved) { const c = tools.find((x) => x.id === events.find((e) => e.id === ev.id)?.call_id); if (c) c.refused = true; }
        else if (ev.type === 'usage') a.usage = { prompt_tokens: ev.prompt_tokens, output_tokens: ev.output_tokens, latency_ms: ev.latency_ms, server_duration_ms: ev.server_duration_ms };
        else if (ev.type === 'title') s.title = ev.title;
      }
      const n = s.items.filter((i) => i.kind === 'user').length + 1;
      s.items.push({ kind: 'user', n, text, at }, a);
      s.usage = { prompt_tokens: sum(s.usage.prompt_tokens, a.usage?.prompt_tokens), output_tokens: sum(s.usage.output_tokens, a.usage?.output_tokens), turns: s.usage.turns + 1, last_prompt_tokens: a.usage?.prompt_tokens ?? null };
      s.saved = true;
      s.updated_at = now();
      saved.set(s.id, s);
    },
  };
  return api;
}
