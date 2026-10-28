// DOM-free self tests: NDJSON parser, stream layer and formatters. Runs in the browser and in Node.
import { NdjsonParser, streamNdjson } from './stream.js';
import { formatNumber, formatPercent, formatTokens, formatDuration, truncateMiddle, wordCount, formatUtc, relativeTime } from './format.js';
import { stripInvisible } from './safetext.js';
import { setLang } from './i18n.js';

const eq = (a, b, msg = '') => { if (JSON.stringify(a) !== JSON.stringify(b)) throw new Error(`${msg} expected ${JSON.stringify(b)}, got ${JSON.stringify(a)}`); };
const throwsCode = (fn, code) => { try { fn(); } catch (e) { eq(e.code, code, 'error code'); return; } throw new Error('did not throw'); };
const enc = new TextEncoder();
const streamOf = (chunks) => new ReadableStream({ start(c) { chunks.forEach((b) => c.enqueue(b)); c.close(); } });
const fakeFetch = (chunks, ok = true) => async () => ({ ok, status: ok ? 200 : 500, body: streamOf(chunks), json: async () => ({ error: { code: 'llm_error', message: 'boom' } }) });
const run = async (chunks) => { const got = []; await streamNdjson('/x', { body: {}, onEvent: (e) => got.push(e), fetchImpl: fakeFetch(chunks) }); return got; };

export const PURE_TESTS = [
  ['setup: English strings loaded', async () => { await setLang('en'); }],
  ['ndjson: whole lines', () => { const p = new NdjsonParser(); eq(p.push('{"a":1}\n{"b":2}\n'), [{ a: 1 }, { b: 2 }]); }],
  ['ndjson: line split across chunks', () => { const p = new NdjsonParser(); eq(p.push('{"a":'), []); eq(p.push('1}\n{"b"'), [{ a: 1 }]); eq(p.push(':2}\n'), [{ b: 2 }]); }],
  ['ndjson: empty and blank lines ignored', () => { const p = new NdjsonParser(); eq(p.push('\n\n  \n{"a":1}\n\n'), [{ a: 1 }]); }],
  ['ndjson: flush parses a final line without newline', () => { const p = new NdjsonParser(); eq(p.push('{"a":1}'), []); eq(p.flush(), [{ a: 1 }]); }],
  ['ndjson: unicode and emoji text', () => { const p = new NdjsonParser(); eq(p.push('{"t":"Rédaction \u{1F9F4} 先"}\n'), [{ t: 'Rédaction \u{1F9F4} 先' }]); }],
  ['ndjson: malformed line throws invalid_response', () => { throwsCode(() => new NdjsonParser().push('{nope}\n'), 'invalid_response'); }],
  ['stream: multi-byte character split across chunks', async () => {
    const bytes = enc.encode('{"type":"text","delta":"é先"}\n{"type":"done","status":"completed"}\n');
    const cut = bytes.indexOf(0xc3) + 1;
    const got = await run([bytes.slice(0, cut), bytes.slice(cut)]);
    eq(got[0].delta, 'é先');
  }],
  ['stream: byte-by-byte delivery', async () => { const b = enc.encode('{"type":"text","delta":"先"}\n{"type":"done"}\n'); eq((await run([...b].map((x) => new Uint8Array([x])))).length, 2); }],
  ['stream: ends without done is a network error', async () => { try { await run([enc.encode('{"type":"text","delta":"x"}\n')]); } catch (e) { eq(e.code, 'network'); return; } throw new Error('did not throw'); }],
  ['stream: unknown event types pass through', async () => { eq((await run([enc.encode('{"type":"future"}\n{"type":"done"}\n')])).map((e) => e.type), ['future', 'done']); }],
  ['stream: non-ok response becomes ApiError', async () => { try { await streamNdjson('/x', { body: {}, onEvent() {}, fetchImpl: fakeFetch([], false) }); } catch (e) { eq([e.code, e.status], ['llm_error', 500]); return; } throw new Error('did not throw'); }],
  ['format: unknown numbers are n/a, never 0', () => { eq(formatNumber(null), 'n/a'); eq(formatNumber(undefined), 'n/a'); eq(formatPercent(null), 'n/a'); eq(formatDuration(null), 'n/a'); }],
  ['format: token chips', () => { eq(formatTokens(212, 85), '212 in / 85 out'); eq(formatTokens(null, null), 'tokens n/a'); eq(formatTokens(null, 85), 'n/a in / 85 out'); eq(formatTokens(0, 0), '0 in / 0 out'); }],
  ['format: thousands separators and percent', () => { eq(formatNumber(4096).replace(/\s/g, ' ').includes('4'), true); eq(formatPercent(15, 1).endsWith('%'), true); }],
  ['format: durations', () => { eq(formatDuration(120), '120 ms'); eq(formatDuration(3200), '3.2 s'); eq(formatDuration(15000), '15 s'); eq(formatDuration(125000), '2 min 5 s'); }],
  ['format: truncateMiddle, wordCount, formatUtc', () => { eq(truncateMiddle('abcdefghij', 5), 'ab…ij'); eq(wordCount('  two words\nhere '), 3); eq(formatUtc('2026-10-20T14:02:00Z'), '2026-10-20 14:02 UTC'); eq(formatUtc('bad'), 'n/a'); }],
  ['format: relativeTime', () => { eq(relativeTime('2026-10-20T10:00:00Z', Date.parse('2026-10-20T10:00:20Z')), 'just now'); }],
  ['safetext: invisible and bidi controls stripped from titles', () => { eq(stripInvisible('  a‮b​c\x1b '), 'abc'); }],
];
