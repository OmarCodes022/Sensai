// Plays an event script with latency, bursts and pauses. Approvals block until the UI answers.
import { ApiError } from '../errors.js';

export const SPEED = { slow: 2.2, normal: 1, fast: 0.3, instant: 0 };
export const abortError = () => Object.assign(new Error('aborted'), { name: 'AbortError' });

export function sleep(ms, signal) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(abortError());
    const id = setTimeout(resolve, ms);
    signal?.addEventListener('abort', () => { clearTimeout(id); reject(abortError()); }, { once: true });
  });
}

const fill = (ev, map) => JSON.parse(JSON.stringify(ev), (k, v) => (typeof v === 'string' && v in map ? map[v] : v));
const DEFAULT_DELAY = { text: 30, tool_call: 300, tool_result: 300, usage: 80 };

/** Returns the final done status (or null). Throws AbortError, or ApiError('network') for a scripted drop. */
export async function play(events, { ctx, speed = 'normal', signal, onEvent, awaitApproval }) {
  const k = typeof speed === 'number' ? speed : SPEED[speed] ?? 1;
  const map = { $id: ctx.turnId, $persona: ctx.persona, $n: ctx.number, $sid: ctx.sid };
  let status = null;
  for (const raw of events.flat(Infinity)) {
    if (raw.type === 'wait') { await sleep(raw.ms * k, signal); continue; }
    if (raw.type === 'drop') throw new ApiError('network', 'stream ended without done');
    if (raw.type === '$saved') {
      if (ctx.skipSave || ctx.saved) continue;
      ctx.saved = true;
      onEvent({ type: 'saved', session_id: ctx.sid });
      continue;
    }
    const { on_approve, on_refuse, delay_ms, ...rest } = raw;
    await sleep((delay_ms ?? DEFAULT_DELAY[raw.type] ?? 100) * k, signal);
    const ev = fill(rest, map);
    if (ev.type === 'warning' && ev.code === 'storage') ctx.skipSave = true;
    onEvent(ev);
    if (ev.type === 'done') status = ev.status;
    if (ev.type === 'approval_request') {
      const approved = await awaitApproval(ev.id, signal);
      onEvent({ type: 'approval_result', id: ev.id, approved });
      status = (await play(approved ? on_approve || [] : on_refuse || [], { ctx, speed, signal, onEvent, awaitApproval })) || status;
    }
  }
  return status;
}
