import { ApiError, errorFromResponse } from './errors.js';

/** Splits text into JSON lines. Tolerates partial lines and empty lines. */
export class NdjsonParser {
  constructor() { this.buf = ''; }
  /** Returns parsed objects; throws ApiError('invalid_response') on a malformed line. */
  push(text) {
    this.buf += text;
    const lines = this.buf.split('\n');
    this.buf = lines.pop();
    return lines.flatMap((l) => this.parseLine(l));
  }
  flush() {
    const rest = this.buf;
    this.buf = '';
    return this.parseLine(rest);
  }
  parseLine(line) {
    if (!line.trim()) return [];
    try { return [JSON.parse(line)]; }
    catch { throw new ApiError('invalid_response', 'invalid response from server'); }
  }
}

/** POSTs and reads an NDJSON stream; calls onEvent per object. Resolves after a `done` event. */
export async function streamNdjson(url, { body, signal, onEvent, fetchImpl = fetch, headers = {} }) {
  let res;
  try {
    res = await fetchImpl(url, { method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal });
  } catch (e) {
    if (e.name === 'AbortError') throw e;
    throw new ApiError('network', 'network error');
  }
  if (!res.ok) throw await errorFromResponse(res);
  const reader = res.body.getReader();
  const dec = new TextDecoder('utf-8');
  const parser = new NdjsonParser();
  let done = false;
  const emit = (events) => events.forEach((ev) => { if (ev.type === 'done') done = true; onEvent(ev); });
  try {
    for (;;) {
      const { value, done: end } = await reader.read();
      if (end) break;
      emit(parser.push(dec.decode(value, { stream: true })));
    }
    emit(parser.push(dec.decode()));
    emit(parser.flush());
  } catch (e) {
    if (e.name === 'AbortError' || e instanceof ApiError) throw e;
    throw new ApiError('network', 'network error');
  }
  if (!done) throw new ApiError('network', 'stream ended without done');
}
