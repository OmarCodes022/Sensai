// Scenario 24: /think with a tool round, a problem, a revision and a passing check (events as the backend sends them).
import { say, usage, title, turn, call, result } from './script.js';

const section = (name, delay_ms = 300) => ({ type: 'think_section', title: name, delay_ms });
const line = (delta, delay_ms = 120) => ({ type: 'text', delta, delay_ms });
const PLAN = '1. Compute the engagement rate with the calculator\n2. Use only approved claims for Hydra Glow Serum\n3. Write the summary and a short, warm caption\n';
const DRAFT = '15% of reached accounts engaged last week. "Hydra Glow Serum cures dry skin and eczema!"';
const ANSWER = '15% of reached accounts engaged last week. "Hydra Glow Serum keeps your skin hydrated for up to 8 hours."';
const PROBLEM = '"cures dry skin and eczema" is not an approved claim';

/** One /think turn. Titles are the backend's English labels (the check titles hold an em dash, written as an escape). */
export const thinkTurn = () => turn(null, [
  section('Plan'), say(PLAN),
  call('c1', 'calculate', { expression: '630 / 4200 * 100' }), result('c1', 'calculate', true, { output: '15.0' }),
  line('I will compute the rate first.\n'),
  section('Act', 50), line('calculate({"expression":"630 / 4200 * 100"})\n', 20), section('Observe', 50), line('15.0\n', 20),
  section('Draft'), line(`${DRAFT}\n`, 500),
  section('Check \u2014 1 problem', 1200), line(`- ${PROBLEM}\n`),
  section('Revise'), line(`${ANSWER}\n`, 500),
  section('Check \u2014 ok', 1200),
  section('Final answer (2 rounds, 1 tool call)'), line(`${ANSWER}\n`),
  { type: 'think_done', answer: ANSWER, rounds: 2, tool_calls: 1, unresolved: [], checked: true, delay_ms: 50 },
  usage(1450, 260, 14200, 13800), title('Weekly engagement and caption'),
]);

export const THINK = [
  { id: 'think', n: 24, think: true, title: '/think: tool, problem, revise, ok', persona: 'analyse',
    prompt: "/think Summarize last week's engagement (630 of 4,200 accounts engaged) and suggest a caption for Hydra Glow Serum",
    notes: 'The steps stream, then fold into "Reasoning: 2 rounds, 1 tool call". Only the request and the final answer are saved.',
    turns: [thinkTurn] },
];
