// Mock fixtures for the planned Campaign view (spec 9.1). Nadia, Serein Studio, week 2026-W44.
export const WEEK = { id: '2026-W44', range: 'Mon 26 Oct to Sun 1 Nov', tz: 'Europe/Paris', file: 'campaigns/2026-W44.json' };
export const SECTIONS = [['posts', 'draft'], ['dm', 'draft'], ['report', 'approved'], ['calendar', 'draft']];

export const POSTS = [
  { id: 'P1', text: 'Thirsty skin? Hydra Glow Serum hydrates skin for up to 8 hours.', claim: { id: 'C01', ok: true, note: 'approved, valid to 2027-06-01' } },
  { id: 'P2', text: 'Finally found something that cures eczema!', claim: { id: 'C02', ok: false, note: 'not approved: no source' } },
  { id: 'P3', text: 'Calm Barrier Cream reduces redness in 4 weeks.', claim: { id: 'C03', ok: true, note: 'approved, valid to 2027-12-01' } },
];
export const DMS = [
  { id: 'Q1', q: 'Does the serum work on dry skin?', reply: 'Hello! Hydra Glow Serum hydrates skin for up to 8 hours, which many people with dry skin enjoy.' },
  { id: 'Q2', q: 'How long does shipping take?', reply: 'Thank you for asking! Orders usually leave within two working days. You will get tracking by email.' },
];
export const LEFT_OUT = ['contact details', 'health detail'];

export const REPORT = {
  period: '21-27 Sep 2026', tz: 'Europe/Paris', source: 'instagram_insights_weekly_unique', reached: 4200, engaged: 630, rate: 15.0,
  formula: 'accounts_engaged / accounts_reached x 100',
  note: 'Engagement was highest on Friday, when the carousel was posted. One week is a small sample, so treat this as a hypothesis to test next week.',
};
export const DAILY = [['21 Sep', 1200, 180], ['22 Sep', 950, 95], ['23 Sep', 1100, 143], ['24 Sep', 800, 72], ['25 Sep', 1300, 195], ['26 Sep', 750, 60], ['27 Sep', 1050, 126], ['28 Sep', 0, 0]];

export const DAYS = ['Mon 2', 'Tue 3', 'Wed 4', 'Thu 5', 'Fri 6', 'Sat 7', 'Sun 8'];
export const ENTRIES = [{ day: 1, time: '18:00', post: 'P1', theme: 'Launch' }, { day: 3, time: '12:30', post: 'P3', theme: 'Redness' }, { day: 5, time: '10:00', post: 'P1', theme: 'Weekend reminder' }];

export const RUN = [['Posts', 'OK', '3 drafts (claims C01, C03)'], ['DM replies', 'OK', '2 suggestions, 2 left out'], ['Report', 'OK', 'reached 4,200 engaged 630 rate 15.0%'], ['Calendar', 'OK', '3 entries Tue 3 Nov to Sat 7 Nov']];
export const EDIT = { cmd: '/campaign posts make P1 more playful', target: 'P1', before: POSTS[0].text, after: 'Thirsty skin? Meet Hydra Glow Serum: up to 8 hours of hydration, one light layer.' };
