// Scenario registry and plain JSON event-script export (replay for fallback videos and backend traces).
import { BASIC } from './scen-basic.js';
import { PYTHON } from './scen-python.js';
import { ERRSCEN, ERRORS, errorTurn } from './scen-errors.js';
import { PERSONA } from './scen-persona.js';
import { PLANNED } from './scen-planned.js';

export { ERRORS, errorTurn };
export const SCENARIOS = [...BASIC, ...PYTHON, ...ERRSCEN, ...PERSONA, ...PLANNED].sort((a, b) => a.n - b.n);
export const byId = (id) => SCENARIOS.find((s) => s.id === id) || SCENARIOS[0];

/** JSON-safe export: each turn is an event array; approval branches stay in on_approve / on_refuse. */
export function exportScript(id) {
  const s = byId(id);
  return {
    id: s.id, number: s.n, title: s.title, persona: s.persona || null, planned: !!s.planned, prompt: s.prompt, notes: s.notes || null,
    format: 'Events follow the sensai chat stream (web/web-ui.md). Extras: delay_ms, wait, drop, $saved, on_approve, on_refuse.',
    turns: s.turns.map((turn) => (typeof turn === 'function' ? turn(s.prompt) : turn)),
  };
}
