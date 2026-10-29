// Scenarios 1-3 plus a stress reply: plain streaming, renderer test, calculate tool.
import { say, usage, title, turn, call, result } from './script.js';

const CAPTIONS = `Here are two caption variants. Both use only the approved claim C01: "Hydrates skin for up to 8 hours".

**Variant A (warm)**
Thirsty skin? Hydra Glow Serum hydrates skin for up to 8 hours. Simple, honest, gentle. #SereinStudio

**Variant B (short)**
One serum, a full day of comfort. Hydrates skin for up to 8 hours.

Nothing was sent or published. These are drafts for you to review.`;

const LONG = `## Launch week plan

A calm plan for the **Calm Barrier Cream** launch, written to test every renderer feature.

### Principles
- Warm, simple, honest, *no medical promises*
- Use only approved claims:
  - C01 "Hydrates skin for up to 8 hours"
  - C03 "Reduces redness in 4 weeks"
- Show aggregate figures only

### Schedule
| Day | Format | Claim | Status |
|:----|:------:|------:|--------|
| Mon | Reel | C03 | Draft |
| Wed | Carousel | C01 | Draft |
| Fri | Story | C01 | Idea |

1. Draft the three posts
2. Review the claims register
3. Approve each draft yourself

> Nothing here is scheduled. Every post waits for your approval.

Tracking snippet, in a code block:

\`\`\`python
reach = [1200, 950, 1100]
print(sum(reach) / len(reach))
\`\`\`

Read the [Instagram help centre](https://help.instagram.com) for format rules, or write to \`hello@example.com\`. Raw <b>HTML</b> stays literal text.

---

That is the whole plan.`;

const para = 'Hydra Glow Serum is a light serum that hydrates skin for up to 8 hours, written here as filler to test long streaming and scrolling behaviour. ';

export const BASIC = [
  { id: 'happy', n: 1, title: 'Happy path', persona: 'redaction', prompt: 'Write 2 caption variants for Hydra Glow Serum using only approved claims',
    turns: [turn(null, [say(CAPTIONS), title('Caption ideas for Hydra Glow'), usage(212, 85)])] },
  { id: 'markdown', n: 2, title: 'Long markdown reply (tokens n/a)', persona: 'redaction', prompt: 'Plan the Calm Barrier Cream launch week in Markdown',
    turns: [turn(null, [say(LONG, 0.6), title('Launch week plan'), usage(null, null, 5400, null)])] },
  { id: 'calculate', n: 3, title: 'Tool: calculate', persona: 'analyse', prompt: 'What is the engagement rate if 630 of 4,200 accounts engaged?',
    turns: [turn(null, [say('Let me calculate that. '), call('c1', 'calculate', { expression: '630 / 4200 * 100' }),
      result('c1', 'calculate', true, { output: '15.0', duration_ms: 100 }),
      say('The engagement rate is **15.0%**: 630 of 4,200 accounts engaged.'), title('Engagement rate'), usage(264, 41, 2100, 1900)])] },
  { id: 'stress', n: 29, title: 'Stress: 5,000-word reply', persona: 'redaction', prompt: 'Write a very long reply',
    turns: [turn(null, [Array.from({ length: 5 }, (_, i) => say(`### Part ${i + 1}\n\n${para.repeat(40)}\n\n`, 0)), usage(900, 6500, 9000, 8800)])] },
];
