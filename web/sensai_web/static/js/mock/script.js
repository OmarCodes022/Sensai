// Helpers that build plain JSON event scripts (spec 12.3). delay_ms is a replay hint; the player scales it.
const pause = (tok, i) => (/[.?!:]\s*$/.test(tok) ? 220 : i % 11 < 4 ? 8 : 30 + ((i * 37) % 55));

/** Splits prose into token-sized text events with deterministic bursts and pauses. */
export function say(text, pace = 1) {
  return (text.match(/\S+\s*|\s+/g) || []).map((delta, i) => ({ type: 'text', delta, delay_ms: Math.round(pause(delta, i) * pace) }));
}
export const usage = (p = 212, o = 85, latency = 3200, server = 3000) => ({ type: 'usage', prompt_tokens: p, output_tokens: o, latency_ms: latency, server_duration_ms: server });
export const wait = (ms) => ({ type: 'wait', ms });
export const title = (text) => ({ type: 'title', title: text });
export const call = (id, name, args, round = 1, extra = {}) => ({ type: 'tool_call', id, name, arguments: args, round, delay_ms: 350, ...extra });
export const result = (id, name, ok, extra = {}) => ({ type: 'tool_result', id, name, ok, error: null, output: '', duration_ms: 100, delay_ms: 400, ...extra });

export function preview(code, { max = 6 } = {}) {
  const lines = code.split('\n');
  return { lines: lines.slice(0, max).map((text) => ({ header: 'code:', text })), hidden_lines: Math.max(0, lines.length - max), incomplete: lines.length > max };
}
export const approval = (id, callId, code, on_approve, on_refuse, extra = {}) => ({
  type: 'approval_request', id, call_id: callId, action: 'run_python', reason: 'The model wants to run code on your computer.',
  preview: preview(code), on_approve, on_refuse, delay_ms: 300, ...extra,
});

/** Wraps parts in turn_start ... done. Placeholders ($id, $persona, $n, $sid) are filled by the player. */
export function turn(persona, parts, { status = 'completed', budget, errorOnly = false, think = false } = {}) {
  const start = { type: 'turn_start', turn_id: '$id', model: 'gemma3:1b', persona: persona || '$persona', number: '$n', ...(budget ? { budget_seconds: budget } : {}), ...(think ? { think: true } : {}) };
  const tail = errorOnly || status === 'dropped' ? [] : [...(status === 'completed' ? [{ type: '$saved' }] : []), { type: 'done', status, turn_id: '$id' }];
  return [start, wait(700), ...parts.flat(Infinity), ...tail];
}
