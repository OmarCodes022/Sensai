// Scenario 24: /think with a tool round, a problem, a revision and a passing check (events as POST /api/think sends them).
import { say, usage, title, turn, call, result } from './script.js';

const heading = (name, delay_ms = 300) => ({ type: 'text', delta: `\n\n**${name}**\n\n`, delay_ms });
const PLAN = '1. Compute the engagement rate with the calculator\n2. Use only approved claims for Hydra Glow Serum\n3. Write the summary and a short, warm caption\n';
const DRAFT = '15% of reached accounts engaged last week. "Hydra Glow Serum cures dry skin and eczema!"';
export const THINK_ANSWER = '15% of reached accounts engaged last week. "Hydra Glow Serum keeps your skin hydrated for up to 8 hours."';
const PROBLEM = '"cures dry skin and eczema" is not an approved claim';

/** One /think turn. The check titles hold an em dash, written as an escape. */
export const thinkTurn = () => turn(null, [
  heading('Plan'), say(PLAN),
  call('c1', 'calculate', { expression: '630 / 4200 * 100' }), result('c1', 'calculate', true, { output: '15.0' }),
  heading('Draft'), say(`${DRAFT}\n`),
  heading('Check — 1 problem', 1200), say(`- ${PROBLEM}\n`),
  heading('Revise'), say(`${THINK_ANSWER}\n`),
  heading('Check — ok', 1200),
  heading('Final answer (2 rounds, 1 tool call)'), say(`${THINK_ANSWER}\n`),
  usage(1450, 260, 14200, 13800), title('Weekly engagement and caption'),
], { think: true });

export const THINK = [
  { id: 'think', n: 24, title: '/think: tool, problem, revise, ok', persona: 'analyse',
    prompt: "/think Summarize last week's engagement (630 of 4,200 accounts engaged) and suggest a caption for Hydra Glow Serum",
    notes: 'The steps show as headings in the reply. Only the request and the final answer are saved.',
    turns: [] },
];
