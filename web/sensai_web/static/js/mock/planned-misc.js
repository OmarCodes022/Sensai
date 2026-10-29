// Mock fixtures for planned Brand, Documents, Insights, Safety and Schedule previews. Reference date: 2026-10-26.
export const TODAY = '2026-10-26';
export const CLAIMS = [
  { id: 'C01', product: 'Hydra Glow Serum', text: 'Hydrates skin for up to 8 hours', source: 'Lab report 2026-03', from: '2026-06-01', until: '2027-06-01', approved: true },
  { id: 'C03', product: 'Calm Barrier Cream', text: 'Reduces redness in 4 weeks', source: 'Clinical summary 2026-05', from: '2026-07-01', until: '2027-12-01', approved: true },
  { id: 'C04', product: 'Hydra Glow Serum', text: 'Suitable for sensitive skin', source: 'Dermatologist note', from: '2025-09-01', until: '2026-09-30', approved: true },
  { id: 'C05', product: 'Calm Barrier Cream', text: 'Soothes tight skin', source: 'Supplier sheet', from: '2026-01-15', until: '2026-12-31', approved: true },
  { id: 'C02', product: 'Calm Barrier Cream', text: 'Cures eczema', source: null, from: null, until: null, approved: false },
];
export const FACTS = [
  { id: 'hydra-glow-serum.launch-date', text: 'Launch on 2026-11-03', source: 'chat 2026-10-20', updated: '2026-10-20' },
  { id: 'brand.tone', text: 'Warm, simple, honest, no medical promises', source: 'chat 2026-10-12', updated: '2026-10-12' },
  { id: 'calm-barrier-cream.size', text: '50 ml tube', source: 'chat 2026-10-18', updated: '2026-10-18' },
];
export const DOCS = [
  { id: 'hydra-glow-serum', type: 'Product sheet', product: 'Hydra Glow Serum', version: '2026-09-01', chunks: 14 },
  { id: 'calm-barrier-cream', type: 'Product sheet', product: 'Calm Barrier Cream', version: '2026-08-15', chunks: 11 },
  { id: 'brand-voice', type: 'Guidelines', product: 'Serein Studio', version: '2026-06-02', chunks: 9 },
];
export const CHUNKS = [
  { source: 'hydra-glow-serum', version: '2026-09-01', text: 'Hydra Glow Serum hydrates skin for up to 8 hours. Apply two drops morning and evening.' },
  { source: 'calm-barrier-cream', version: '2026-08-15', text: 'Calm Barrier Cream reduces redness in 4 weeks when used twice a day on clean skin.' },
  { source: 'brand-voice', version: '2026-06-02', text: 'Our voice is warm and simple. We never make medical promises and we avoid superlatives.' },
  { source: 'hydra-glow-serum', version: '2026-09-01', text: 'Texture: light gel serum, fragrance free, suitable for daily use.' },
];
export const STATS = { calls: 128, errors: 6, latencyMs: 3150, promptTokens: 21400, outputTokens: null };
export const PER_DAY = [['2026-10-20', 14, 0, 2900], ['2026-10-21', 22, 1, 3300], ['2026-10-22', 19, 2, 3600], ['2026-10-23', 25, 1, 3000], ['2026-10-24', 31, 2, 3200], ['2026-10-25', 17, 0, 2800]];
export const TOOL_USE = [['calculate', 41, 0], ['run_python', 12, 3]];
export const KINDS = ['chat', 'title', 'summary'];

export const RULES = [['input', 'redact', 'private_identifier'], ['input', 'refuse', 'sensitive_detail'], ['output', 'refuse', 'unsupported_claim'], ['input', 'allow', 'unsafe_request']];
export const SUITE = [['Prompt injection', 6, 5, 1, 0], ['Private data', 6, 6, 0, 0], ['Medical claims', 6, 4, 0, 2], ['Impersonation', 6, 6, 0, 0], ['Tool abuse', 6, 3, 1, 2], ['Data exfiltration', 5, 5, 0, 0]];
export const EVAL = { relevance: [4, 5], coherence: [4, 4], faithfulness: [3, 5], flagged: [['Hydrates for 12 hours', 'unsupported'], ['No irritation reported', 'contradicted']], misses: 1, falseAlarms: 0, versions: ['2026-09-01', '2026-10-10'] };

export const TASKS = [
  { name: 'Weekly report draft', prompt: 'Prepare the weekly report', persona: 'analyse', every: 10080, last: '2026-10-26 07:00', next: '2026-11-02 07:00', status: 'ok' },
  { name: 'DM reply suggestions', prompt: 'Suggest unsent replies', persona: 'communaute', every: 1440, last: '2026-10-26 08:00', next: 'in 60 min (retry)', status: 'failed' },
  { name: 'Post drafts', prompt: 'Draft three posts', persona: 'redaction', every: 10080, last: '2026-10-19 07:30', next: '2026-11-02 07:30', status: 'ok' },
];
export const DRAFTS = [['report-2026-W43.md', 'Weekly engagement was 15.0 percent. Reach 4,200, engaged 630.'], ['posts-2026-W44.md', 'P1: Thirsty skin? Hydra Glow Serum hydrates skin for up to 8 hours.']];
