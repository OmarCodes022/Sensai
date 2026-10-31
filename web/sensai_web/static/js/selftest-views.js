// Self tests for the view logic added with the live and planned views. Browser only (views import DOM helpers).
import { validateProfile } from './profile/validate.js';
import { claimStatus } from './views/preview/brand.js';
import { score } from './views/preview/documents.js';
import { rate } from './views/preview/campaign-report.js';
import { toResult } from './tools/sandbox.js';
import { effectiveRows, SECRET } from './settings/config-rows.js';
import { stripInvisible, visibleEscapes } from './safetext.js';
import { createToolCard } from './chat/tool-card.js';
import { pythonBody } from './chat/py-card.js';
import { createAssistant } from './chat/assistant.js';
import { parseHash } from './router.js';
import { formatNumber, formatDuration, formatPercent } from './format.js';

const eq = (a, b, m = '') => { if (JSON.stringify(a) !== JSON.stringify(b)) throw new Error(`${m} expected ${JSON.stringify(b)}, got ${JSON.stringify(a)}`); };

export const VIEW_TESTS = [
  ['profile: object of strings is valid', () => eq(validateProfile('{"ton":"direct"}').value, { ton: 'direct' })],
  ['profile: non-string value reports its line', () => eq(validateProfile('{\n "a": "x",\n "b": 2\n}').errors, [{ line: 3, key: 'notString', args: { name: 'b' } }])],
  ['profile: arrays, null and empty are rejected', () => { eq(validateProfile('[]').errors[0].key, 'notObject'); eq(validateProfile('null').errors[0].key, 'notObject'); eq(validateProfile(' ').errors[0].key, 'empty'); }],
  ['profile: syntax error is reported', () => eq(validateProfile('{nope}').errors[0].key, 'syntax')],
  ['brand: claim status from dates', () => {
    eq(claimStatus({ approved: false }), ['rose', 'notApproved']);
    eq(claimStatus({ approved: true, until: '2026-09-30' }, '2026-10-26'), ['rose', 'expired']);
    eq(claimStatus({ approved: true, until: '2026-12-31' }, '2026-10-26'), ['amber', 'expiring']);
    eq(claimStatus({ approved: true, until: '2027-06-01' }, '2026-10-26'), ['sage', 'valid']);
  }],
  ['report: zero reach has no rate (n/a, never 0)', () => { eq(rate(0, 0), null); eq(rate(4200, 630), 15); }],
  ['documents: search score is word overlap', () => { eq(score('hydration', 'no match here'), 0); eq(score('serum hydrates', 'The serum hydrates skin'), 1); }],
  ['sandbox: run output maps to a tool result', () => {
    const r = toResult({ exit_code: -9, duration_s: 15, timed_out: true, stdout: '', stderr: '', report: 'x' });
    eq([r.ok, r.meta.timed_out, r.duration_ms], [false, true, 15000]);
  }],
  ['settings: secret-looking keys are masked, others are not', () => { eq(['api_key', 'auth_token', 'client_secret', 'password'].every((k) => SECRET.test(k)), true); eq(['model', 'creator', 'data_dir'].some((k) => SECRET.test(k)), false); }],
  ['settings: rows fall back to flat config and report unknown as null', () => {
    const rows = effectiveRows({ model: 'm', context_length: 4096 });
    eq([rows.find((r) => r.key === 'model').value, rows.find((r) => r.key === 'prompt_file').value, rows.find((r) => r.key === 'model').source], ['m', undefined, null]);
  }],
  ['safetext: tag chars, ALM, LS/PS, soft hyphen, CGJ, variation selectors, Hangul fillers are stripped', () => {
    const bad = ['\u{E0041}', '\u061C', '\u2028', '\u2029', '\u00AD', '\u034F', '\u180E', '\uFE0F', '\u3164', '\u115F', '\u1160', '\u202E'];
    for (const c of bad) eq(stripInvisible(`a${c}b`), 'ab', `U+${c.codePointAt(0).toString(16)}`);
    eq(stripInvisible('a\u00A0b'), 'a\u00A0b', 'nbsp kept in prose');
  }],
  ['safetext: visibleEscapes shows chips, NBSP only when asked', () => {
    const box = document.createElement('div');
    box.append(visibleEscapes('a\u{E0041}b\u061Cc\u00A0d'));
    eq([...box.querySelectorAll('.chip')].map((c) => c.textContent), ['U+E0041', 'U+061C', 'U+00A0']);
    const prose = document.createElement('div');
    prose.append(visibleEscapes('a\u00A0b', { nbsp: false }));
    eq(prose.querySelectorAll('.chip').length, 0);
  }],
  ['tool card: bidi and hidden characters in name, summary and error are visible chips', () => {
    const card = createToolCard({ id: 'c1', name: 'run\u202E_python\u061C', arguments: { expression: '1\u2028+1' }, round: 1 });
    card.setResult({ ok: false, error: 'bad\u202Eerror', output: '', duration_ms: 5, meta: {} });
    const text = card.el.textContent;
    if (/[\u202E\u061C\u2028]/.test(text)) throw new Error('raw control character reached the DOM text');
    if (card.el.querySelectorAll('.chip--rose').length < 3) throw new Error('expected escape chips');
  }],
  ['router: malformed percent-encoding falls back to not found', () => { eq(parseHash('#/chat/%E0%A4%A').name, null); eq(parseHash('#/chat/ab%20c').params.id, 'ab c'); }],
  ['format: only finite numbers are known', () => {
    for (const v of ['', false, [], '5', {}, NaN, Infinity, null, undefined]) eq(formatNumber(v), 'n/a', String(v));
    eq([formatDuration(''), formatPercent(false)], ['n/a', 'n/a']);
    eq(formatNumber(0), '0');
  }],
  ['sandbox: missing duration is n/a, not 0', () => { const r = toResult({ exit_code: 0, stdout: '' }); eq(r.duration_ms, null); eq(formatDuration(r.duration_ms), 'n/a'); }],
  ['tool card: run_python shows Run n of 3, says the last one, and a stopped call has no run', () => {
    const at = (n) => ({ attempt: n, max_attempts: 3 });
    const runCard = (n, r) => { const c = createToolCard({ id: `c${n}`, name: 'run_python', arguments: { code: 'print(1)' }, round: n, ...at(n) }); c.setResult({ ...r, ...at(n) }); c.expand(); return c; };
    const ok = { ok: true, error: null, output: '1', duration_ms: 5, meta: { exit_code: 0, stdout: '1\n', stderr: '' } };
    eq(runCard(2, ok).el.querySelector('.toolcard__attempt').textContent, 'Run 2 of 3');
    eq(runCard(3, ok).el.querySelector('.toolcard__attempt').textContent, 'Run 3 of 3, the last');
    const stop = runCard(4, { ok: false, error: 'Stopped after 3 attempts: answer with the last result or error, without calling run_python again.', output: '', duration_ms: 0 });
    eq([stop.status(), stop.el.querySelector('.toolcard__attempt').textContent], ['stopped', '']);
    if (!stop.el.textContent.includes('Not run: Sensai stops after 3 runs')) throw new Error('missing stop note');
    if ([...stop.el.querySelectorAll('[role="tab"]')].some((tab) => /Output|Errors/.test(tab.textContent))) throw new Error('a stopped call shows run tabs');
  }],
  ['python card: missing exit code shows n/a, not derived from ok', () => {
    const el = pythonBody({ arguments: { code: 'x' } }, { ok: true, output: '', duration_ms: 1, meta: {} });
    const chips = [...el.querySelectorAll('.chip--mono')].map((c) => c.textContent);
    if (!chips.some((c) => c.includes('n/a')) || chips.some((c) => c === 'Exit code 0')) throw new Error(`chips: ${chips}`);
  }],
  ['an approval reopens a collapsed tool group', () => {
    const block = createAssistant({ persona: { name: 'Sensai', id: 'x' } });
    const group = block.el.querySelector('.toolgroup');
    block.addTool(document.createElement('div'));
    group.open = false;
    block.addTool(document.createElement('div'));
    if (group.open) throw new Error('a tool card must not reopen a group the creator collapsed');
    const card = document.createElement('section');
    block.addApproval(card);
    if (!group.open || !group.contains(card)) throw new Error('the approval stayed hidden');
  }],
];
