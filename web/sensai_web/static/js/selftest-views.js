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
import { parseHash } from './router.js';
import { formatNumber, formatDuration, formatPercent } from './format.js';
import { createReasoning, stepOf, stepLabel, summaryOf } from './chat/reasoning.js';
import { setLang } from './i18n.js';
import { mockApi, control } from './mock/mock-api.js';

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
  ['python card: missing exit code shows n/a, not derived from ok', () => {
    const el = pythonBody({ arguments: { code: 'x' } }, { ok: true, output: '', duration_ms: 1, meta: {} });
    const chips = [...el.querySelectorAll('.chip--mono')].map((c) => c.textContent);
    if (!chips.some((c) => c.includes('n/a')) || chips.some((c) => c === 'Exit code 0')) throw new Error(`chips: ${chips}`);
  }],
  ['think: section titles map to step kinds and page labels', () => {
    eq(['Plan', 'Act', 'Observe', 'Draft', 'Revise', 'Unresolved', 'Check unavailable'].map((x) => stepOf(x).kind), ['plan', 'act', 'observe', 'draft', 'revise', 'unresolved', 'unavailable']);
    eq([stepOf('Check \u2014 ok'), stepOf('Check \u2014 1 problem'), stepOf('Check \u2014 12 problems')], [{ kind: 'ok' }, { kind: 'problems', n: 1 }, { kind: 'problems', n: 12 }]);
    eq([stepOf('Final answer (2 rounds, 1 tool call)').kind, stepOf('constructor').kind, stepOf(null).kind], ['final', 'other', 'other']);
    eq([stepLabel('Check \u2014 2 problems'), stepLabel('Check \u2014 1 problem'), stepLabel('Check \u2014 ok'), stepLabel('<b>New</b>')], ['Check: 2 problems', 'Check: 1 problem', 'Check: ok', '<b>New</b>']);
    eq([summaryOf({ rounds: 2, tool_calls: 1 }), summaryOf({ rounds: 1, tool_calls: 0 })], ['Reasoning: 2 rounds, 1 tool call', 'Reasoning: 1 round, 0 tool calls']);
  }],
  ['think: French labels and plural forms', async () => {
    await setLang('fr');
    try {
      eq([summaryOf({ rounds: 2, tool_calls: 0 }), summaryOf({ rounds: 1, tool_calls: 3 }), stepLabel('Check \u2014 2 problems')], ["Raisonnement : 2 tours, 0 appel d'outil", "Raisonnement : 1 tour, 3 appels d'outil", 'Vérification : 2 problèmes']);
    } finally { await setLang('en'); }
  }],
  ['think: a full turn shows each step once, one card per round, escaped, then folds', () => {
    const r = createReasoning();
    const card = createToolCard({ id: 'c1', name: 'calculate', arguments: { expression: '630 / 4200 * 100' }, round: 1 });
    const approval = document.createElement('section');
    approval.className = 'approval';
    r.section('Plan'); r.text('1. Compute <img src=x onerror=alert(1)>\n');
    r.addTool(card); r.addApproval(approval); card.setResult({ ok: true, output: '15.0', error: null, duration_ms: 3 });
    r.text('Narration before the call.\n');
    r.section('Act'); r.text('calculate({"expression":"630 / 4200 * 100"})\n');
    r.section('Observe'); r.text('15.0 observed\n');
    r.section('Draft'); r.text('Draft answer\n');
    r.section('Check \u2014 1 problem'); r.text('- a problem\n');
    r.section('Revise'); r.text('Final\n');
    r.section('Check \u2014 ok');
    r.section('Final answer (2 rounds, 1 tool call)');
    eq(r.text('Final\n'), false, 'final answer goes to the reply');
    r.done({ rounds: 2, tool_calls: 1 });
    eq([...r.el.querySelectorAll('.reasoning__step')].map((li) => li.dataset.kind), ['plan', 'act', 'observe', 'draft', 'problems', 'revise', 'ok']);
    eq([r.el.querySelectorAll('.toolcard').length, !!r.el.querySelector('[data-kind="act"] .approval')], [1, true]);
    const text = r.el.textContent;
    if (text.includes('calculate({') || text.includes('15.0 observed')) throw new Error('tool text repeated next to its card');
    if (r.el.querySelector('img') || !text.includes('<img src=x onerror=alert(1)>')) throw new Error('model text became markup');
    eq(r.el.querySelector('[data-kind="plan"]').textContent.includes('Narration before the call.'), true, 'narration stays before Act');
    eq(r.el.querySelector('[data-kind="observe"] .chip').textContent, 'OK');
    eq(r.el.querySelector('[data-kind="problems"] li')?.textContent, 'a problem');
    eq([r.el.open, r.el.querySelector('summary').textContent], [false, 'Reasoning: 2 rounds, 1 tool call']);
  }],
  ['think: an approval opens a folded block and lands in its Act step', () => {
    const r = createReasoning();
    r.section('Plan'); r.text('p\n'); r.addTool(createToolCard({ id: 'c1', name: 'run_python', arguments: { code: 'print(1)' }, round: 1 }));
    r.el.open = false;
    const approval = document.createElement('section');
    r.addApproval(approval);
    eq([r.el.open, approval.closest('.reasoning__step')?.dataset.kind], [true, 'act']);
  }],
  ['tool card: without a max (think) the round shows alone', () => {
    const text = createToolCard({ id: 'c6', name: 'calculate', arguments: { expression: '1+1' }, round: 6 }, { max: null }).el.textContent;
    if (!text.includes('Round 6') || text.includes('Round 6 of')) throw new Error(text);
    if (!createToolCard({ id: 'c2', name: 'calculate', arguments: {}, round: 2 }, { max: 5 }).el.textContent.includes('Round 2 of 5')) throw new Error('normal card lost its max');
  }],
  ['mock: think mode always thinks, a normal message never does', async () => {
    const before = { ...control.state };
    control.select('think'); control.set({ speed: 'instant' });
    const run = async (text, mode) => { const got = []; await mockApi.chat(text, { mode, onEvent: (e) => got.push(e.type) }); return got; };
    try {
      eq((await run('plain', undefined)).includes('think_section'), false, 'normal message in scenario 24');
      for (const _ of [1, 2]) eq((await run('again', 'think')).includes('think_done'), true, 'think turn in scenario 24');
      control.select('happy'); control.set({ speed: 'instant' });
      eq((await run('x', 'think')).includes('think_done'), true, 'think turn in another scenario');
    } finally { control.select(before.scenario); control.set({ speed: before.speed }); document.querySelector('.devpanel')?.remove(); }
  }],
  ['think: without a card the call and result lines are kept', () => {
    const r = createReasoning();
    r.section('Plan'); r.text('p\n'); r.section('Act'); r.text('lookup({})\n'); r.section('Observe'); r.text('7\n'); r.stop();
    eq([r.el.querySelector('[data-kind="act"]').textContent.includes('lookup({})'), r.el.querySelector('[data-kind="observe"]').textContent.includes('7'), r.el.open], [true, true, true]);
  }],
];
