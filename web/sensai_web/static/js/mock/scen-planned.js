// Scenarios 21-23 and 25-28 (planned features, compact scripts). Events follow spec 12.3 planned types.
import { say, usage, turn, call, result } from './script.js';

const step = (s, text) => ({ type: 'step', step: s, text, delay_ms: 400 });
const CAMPAIGN_EDIT = { type: 'approval_request', id: 'a1', call_id: 'c1', action: 'campaign_edit', reason: 'The model wants to change an approved section of the weekly plan.',
  preview: { lines: [{ header: 'before:', text: 'P1: "Hydra Glow Serum hydrates skin for up to 8 hours."' }, { header: 'after:', text: 'P1: "Thirsty skin? Eight hours of comfort, one gentle drop."' }], hidden_lines: 0, incomplete: false }, delay_ms: 300,
  on_approve: [say('Done: P1 is now more playful.')], on_refuse: [say('No change made. P1 stays as approved.'), usage(250, 20)] };
const t = (parts) => turn(null, parts);

export const PLANNED = [
  { id: 'guardrails', n: 21, title: 'Guardrails (planned)', planned: true, persona: 'communaute', prompt: 'Reply to this DM from lea@example.com about dry skin',
    turns: [
      t([{ type: 'redacted', parts: [{ class: 'email' }], sent_as: '[redacted] asked: does the serum work on dry skin?' }, say('Suggested reply (unsent): "Hello! Hydra Glow Serum hydrates skin for up to 8 hours, which many people with dry skin enjoy."'), usage(180, 40)]),
      t([{ type: 'blocked', direction: 'input', reason: 'sensitive_detail', message: 'This message mentions a health detail. It was not sent to the model.' }]),
      t([say('Suggested reply: "Our cream '), { type: 'blocked', direction: 'output', reason: 'unapproved_claim', message: 'The draft referred to an unapproved claim (C02).' }])] },
  { id: 'campaign', n: 22, title: 'Campaign week run (planned)', planned: true, persona: 'redaction', prompt: '/campaign posts make P1 more playful',
    turns: [
      t([say('**Weekly run summary**\n\n| Item | Count |\n|---|---:|\n| Posts drafted | 3 |\n| Replies suggested | 2 |\n| DMs left out | 2 |\n\nNothing was sent or published.'), usage(300, 70)]),
      t([call('c1', 'campaign_edit', { section: 'posts', target: 'P1', instruction: 'more playful' }), CAMPAIGN_EDIT])] },
  { id: 'documents', n: 23, title: 'Documents (planned)', planned: true, persona: 'redaction', prompt: 'What does the brand sheet say about hydration?',
    turns: [
      t([call('c1', 'search_docs', { query: 'hydration claim' }), result('c1', 'search_docs', true, { output: 'hydra-glow-serum (2026-09-01): Hydrates skin for up to 8 hours.' }),
        say('According to the product sheet, the serum hydrates skin for up to 8 hours [1].'), { type: 'sources', items: [{ n: 1, source: 'hydra-glow-serum', version: '2026-09-01', score: 0.82 }] }, usage(420, 60)]),
      t([call('c2', 'search_docs', { query: 'vegan certification' }), result('c2', 'search_docs', true, { output: 'No matching passages.' }), say('That is not in the documents, so I cannot answer it.'), usage(380, 20)])] },
  { id: 'team', n: 25, title: '/team (planned)', planned: true, persona: 'redaction', prompt: '/team Plan the launch post',
    turns: [t([step('plan', 'Rédaction drafts, Analyse checks figures, Communauté checks tone'), step('draft', 'Rédaction: draft ready'), step('check', 'Analyse: no figures invented'), say('Draft agreed by all three roles. Review it before use.'), usage(500, 90)])] },
  { id: 'ask-user', n: 26, title: 'ask_user form (planned)', planned: true, persona: 'redaction', prompt: 'Plan a post',
    turns: [t([say('Before I draft, two questions:\n1. Which product: Hydra Glow Serum or Calm Barrier Cream?\n2. Which format: reel, carousel or story?'), usage(150, 30)])] },
  { id: 'summary', n: 27, title: 'Context summary (planned)', planned: true, persona: 'redaction', prompt: 'Continue with the plan',
    turns: [t([{ type: 'warning', code: 'context_summarised', message: 'Earlier messages summarised' }, say('Continuing from the summary: three posts are drafted and waiting for your review.'), usage(1900, 40)])] },
  { id: 'monday', n: 28, title: "Nadia's Monday (keynote)", planned: true, persona: 'analyse', prompt: 'Summarise last week for me',
    notes: ['1 Open Sensai and check status', '2 Analyse: weekly figures with calculate', '3 Switch to Rédaction: 3 drafts', '4 Communauté: DM replies, one left out', '5 Calendar proposal', '6 Refuse a risky action', '7 Roadmap', '8 Honest limits'],
    turns: [
      t([say('Status is green: Ollama ready, model gemma3:1b. Let me read the figures. '), call('c1', 'calculate', { expression: '630 / 4200 * 100' }), result('c1', 'calculate', true, { output: '15.0' }), say('Weekly engagement was **15.0%**.'), usage(260, 50)]),
      t([say('Three drafts using only approved claims C01 and C03:\n1. "Hydrates skin for up to 8 hours."\n2. "Reduces redness in 4 weeks."\n3. "Thirsty skin? Eight gentle hours."'), usage(320, 80)]),
      t([say('Two DM replies are ready (unsent). One DM was left out: contact details.'), usage(280, 60)]),
      t([call('c2', 'campaign_edit', { section: 'posts', target: 'P2' }), { ...CAMPAIGN_EDIT, id: 'a2', call_id: 'c2' }]),
      t([say('What works: chat, personas, sessions, tools. Limits: one tab, small local model, sandbox is not a security boundary. Next: documents, guardrails, campaign.'), usage(300, 70)])] },
];
