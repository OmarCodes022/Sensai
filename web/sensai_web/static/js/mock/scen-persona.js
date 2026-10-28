// Scenarios 17-20: persona switch, resumed session, empty states, single-tab lock.
import { say, usage, title, turn } from './script.js';

const ANALYSE = `**Facts** (from the aggregate figures)
- Weekly reach was 4,200 accounts and 630 engaged, a rate of **15.0%** [1].
- Average daily reach from 21 to 27 September was 1,021.4 accounts.
- On 28 September the reach was 0, so that day's rate is n/a, not 0.

**Interpretation** (my reading, not a measured fact)
- Fridays look strongest, which may be linked to the carousel format.
- One week is a small sample; treat this as a hypothesis to test.

No individual accounts or DMs were used.`;

export const PERSONA = [
  { id: 'persona-switch', n: 17, title: 'Persona switch mid-session', persona: 'redaction', prompt: 'Write a caption for Hydra Glow Serum', notes: 'After the first reply, switch to Analyse with the persona pill, then ask for figures.',
    turns: [
      turn(null, [say('Thirsty skin? Hydra Glow Serum hydrates skin for up to 8 hours.\n\nA draft for your review; nothing was sent.'), title('Hydra Glow caption and weekly figures'), usage(205, 44)]),
      turn(null, [say(ANALYSE, 0.8), { type: 'sources', items: [{ n: 1, source: 'instagram_insights_weekly_unique', version: '2026-09-28', score: 0.91 }] }, usage(388, 142, 5200, 5000)])] },
  { id: 'resume', n: 18, title: 'Resume a saved session (14 messages)', persona: 'redaction', prompt: 'Add one more variant', setup: (c) => c.sessions.setCurrent('k7f2qa'),
    turns: [turn(null, [say('Here is a third variant: "Your skin, quietly hydrated for up to 8 hours."'), usage(402, 31, 2300, 2100)])] },
  { id: 'empty', n: 19, title: 'Empty states', persona: 'redaction', prompt: 'Hello',
    setup: (c) => { c.sessions.fresh(c.persona()); c.state.hideSessions = true; c.state.noTools = true; }, turns: [] },
  { id: 'lock', n: 20, title: 'Single-tab lock (409)', prompt: 'Hello', setup: (c) => { c.state.locked = true; }, turns: [] },
];
