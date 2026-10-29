// Scenarios 9-16 (round limit, interruption, timeout, backend failures) and the error presets for the dev panel.
import { say, usage, turn, call, result, wait } from './script.js';

const HOST = 'http://localhost:11434';
export const ERRORS = {
  connection: { code: 'connection', message: `cannot reach Ollama at ${HOST}, is it running?`, hint: 'ollama serve' },
  model_not_found: { code: 'model_not_found', message: "model 'gemma3:1b' not found", hint: 'ollama pull gemma3:1b' },
  timeout: { code: 'timeout', message: `Ollama at ${HOST} timed out`, hint: null },
  llm_error: { code: 'llm_error', message: 'llama runner process has terminated: signal: killed', hint: null },
  invalid_response: { code: 'invalid_response', message: 'invalid response from Ollama', hint: null },
  profile_invalid: { code: 'profile_invalid', message: 'profile file is invalid: expected an object of strings', hint: null },
  persona_unknown: { code: 'persona_unknown', message: 'unknown persona: marketing', hint: null },
  tab_locked: { code: 'tab_locked', message: 'Sensai is open in another tab.', hint: null },
};
/** Events for one failing turn (no done event, like the real stream). */
export const errorTurn = (code, persona) => turn(persona, [{ type: 'error', ...ERRORS[code] }], { errorOnly: true });
const failing = (code) => () => errorTurn(code, null);

const rates = [['630 / 4200 * 100', '15.0'], ['180 / 1200 * 100', '15.0'], ['95 / 950 * 100', '10.0'], ['143 / 1100 * 100', '13.0'], ['72 / 800 * 100', '9.0']];
const rounds = rates.flatMap(([expr, out], i) => [call(`c${i + 1}`, 'calculate', { expression: expr }, i + 1), result(`c${i + 1}`, 'calculate', true, { output: out, delay_ms: 250 })]);
const slow = 'Posting at a steady rhythm matters more than posting often. For Serein Studio, a calm weekly pattern works well: one educational post, one product moment, one story that answers a real question from the inbox. Keep each caption warm and simple, name the benefit in plain words, and never promise a medical result. Review every draft yourself before anything is published, and keep notes on which format earned the most replies so next week starts from evidence rather than from habit.';

export const ERRSCEN = [
  { id: 'rounds', n: 9, title: 'Tool round limit', persona: 'analyse', prompt: 'Compute the daily engagement rate for each day',
    turns: [turn(null, [say('I will check each day. '), rounds,
      { type: 'warning', code: 'tool_round_limit', message: 'Tool round limit reached.' },
      say('The first five days are 15.0, 15.0, 10.0, 13.0 and 9.0 percent. I stopped there; ask again for the remaining days.'), usage(520, 96, 6100, 5900)])] },
  { id: 'interrupt', n: 10, title: 'Interruption (press Esc)', persona: 'redaction', prompt: 'Explain a posting rhythm for the brand', notes: 'Press Esc or Stop mid-stream.',
    turns: [turn(null, [say(slow, 1.7), usage(200, 120)])] },
  { id: 'turn-timeout', n: 11, title: 'Turn timeout (accelerated to 8 s)', persona: 'redaction', prompt: 'Write a very detailed month plan',
    turns: [turn(null, [say('Starting with week one: choose three themes and match each to an approved claim. ', 1.2), wait(7000)], { status: 'timed_out', budget: 8 })] },
  { id: 'model-missing', n: 12, title: 'Model not installed', prompt: 'Hello', turns: [failing('model_not_found')] },
  { id: 'ollama-down', n: 13, title: 'Ollama unreachable', prompt: 'Hello', turns: [failing('connection')] },
  { id: 'ollama-timeout', n: 14, title: 'Ollama timeout', prompt: 'Hello', turns: [failing('timeout')] },
  { id: 'storage', n: 15, title: 'Storage error (conversation continues)', persona: 'redaction', prompt: 'Write one caption for Hydra Glow Serum',
    turns: [turn(null, [say('Thirsty skin? Hydra Glow Serum hydrates skin for up to 8 hours. '), { type: 'warning', code: 'storage', message: 'database is locked: could not write the session' }, usage(190, 30)])] },
  { id: 'network-drop', n: 16, title: 'Lost connection mid-stream', persona: 'redaction', prompt: 'Write a caption for Calm Barrier Cream',
    turns: [turn(null, [say('Calm Barrier Cream is made for evenings when your skin needs a quiet moment, so '), { type: 'drop' }], { status: 'dropped' })] },
];
