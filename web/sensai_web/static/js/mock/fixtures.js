// Demo fixtures (spec appendix C): Nadia, Serein Studio, Instagram, Europe/Paris. Exact values.
export const PERSONAS = [
  { id: 'redaction', name: 'Rédaction', tone: 'warm', role: 'Drafts posts and captions for validation.', response_scope: 'Drafts only. Nothing is published.',
    starters: ['Write 2 caption variants for Hydra Glow Serum using only approved claims', 'Draft a launch post for Calm Barrier Cream', 'Rewrite this caption to sound warmer'] },
  { id: 'communaute', name: 'Communauté', tone: 'kind', role: 'Suggests unsent replies to comments and DMs.', response_scope: 'Suggestions only. Nothing is sent.',
    starters: ['Suggest an unsent reply to: Does the serum work on dry skin?', 'Reply to a question about shipping times', 'Help me answer a worried follow-up kindly'] },
  { id: 'analyse', name: 'Analyse', tone: 'precise', role: 'Reads aggregate Instagram figures and prepares a weekly report.', response_scope: 'Aggregate figures only.',
    starters: ["Summarise last week's engagement from these figures", 'Explain the zero-reach day on 28 Sep', 'What should we test next week?'] },
];

export const HEALTH = { ok: true, version: '0.1.0', ollama: { reachable: true, host: 'http://localhost:11434', latency_ms: 12 }, model: { name: 'gemma3:1b', available: true }, remote: false };
export const CONFIG = {
  capabilities: { chat: true, personas: true, sessions: true, profile: true, usage: true, tools: true, approval: true, sandbox: true, run_script: true, history: true, documents: true },
  draft_personas: ['redaction', 'communaute'], context_length: 4096, creator: 'default', model: 'gemma3:1b',
  effective: {
    ollama_host: { value: 'http://localhost:11434', source: 'default' }, model: { value: 'gemma3:1b', source: 'cli' }, request_timeout: { value: 120, source: 'default' },
    turn_budget: { value: 120, source: 'default' }, context_length: { value: 4096, source: 'env' }, database_path: { value: '~/.sensai/sensai.db', source: 'default' },
    creator: { value: 'default', source: 'default' }, profile_file: { value: null, source: 'default' }, data_dir: { value: 'tests/fixtures', source: 'env' },
    prompt_file: { value: null, source: 'default' }, personas_file: { value: null, source: 'default' },
  },
  limits: { turn_seconds: 120, tool_rounds: 5, sandbox: { wall_seconds: 15, cpu_seconds: 10, memory_mb: 512, file_mb: 10, output_chars: 10000, data_mb: 50 } },
};
export const PROFILE = { id: 'default', preferences: { name: 'Nadia', ton: 'direct', public: 'créatrices beauté' } };

export const ENGAGEMENT = [
  ['2026-09-21', 1200, 180, '15.0'], ['2026-09-22', 950, 95, '10.0'], ['2026-09-23', 1100, 143, '13.0'], ['2026-09-24', 800, 72, '9.0'],
  ['2026-09-25', 1300, 195, '15.0'], ['2026-09-26', 750, 60, '8.0'], ['2026-09-27', 1050, 126, '12.0'], ['2026-09-28', 0, 0, 'n/a'],
];
export const ENGAGEMENT_CSV = ['date,source,accounts_reached,accounts_engaged,engagement_rate,source_kind']
  .concat(ENGAGEMENT.map(([d, r, e, p]) => `${d},instagram,${r},${e},${p},instagram_insights_daily`))
  .concat('2026-09-21/2026-09-27,instagram,4200,630,15.0,instagram_insights_weekly_unique').join('\n');
export const DATA_FILES = { dir: '/Users/nadia/sensai/data', exists: true, files: [{ name: 'engagement.csv', bytes: 812 }], limits: { file_mb: 10, total_mb: 50, types: ['.csv', '.tsv', '.json', '.txt', '.md'] } };

export const PY_CODE = `import csv
reach = []
for row in csv.DictReader(open("engagement.csv")):
    if row["source"] == "instagram_insights_daily":
        if "2026-09-21" <= row["date"] <= "2026-09-27":
            reach.append(int(row["accounts_reached"]))
print(round(sum(reach) / len(reach), 1))`;
export const PY_CODE_BAD = `import csv
reach = []
for row in csv.DictReader(open("engagement.csv")):
    reach.append(int(row["reach"]))
print(sum(reach) / len(reach))`;

export const TOOLS = [
  { name: 'calculate', description: 'Evaluate an arithmetic expression.', parameters: { expression: 'string' }, timeout: 30, confirm: false, max_calls: null },
  { name: 'run_python', description: 'Run model-written Python in a limited sandbox. Always asks first.', parameters: { code: 'string' }, timeout: 30, confirm: true, max_calls: 3 },
];

const D = (day, h, m = 0) => new Date(Date.UTC(2026, 9, day, h, m)).toISOString();
export const SESSION_META = [
  { id: 'k7f2qa', title: 'Instagram caption for the Hydra Glow launch', persona: 'redaction', messages: 14, created_at: D(25, 8), updated_at: D(25, 13, 40) },
  { id: 'm4tq8z', title: 'Instagram caption for the Hydra Glow launch (branch)', persona: 'redaction', messages: 6, created_at: D(25, 9), updated_at: D(25, 11) },
  { id: 'p9d3wx', title: 'Weekly engagement, 21-27 Sep', persona: 'analyse', messages: 8, created_at: D(24, 9), updated_at: D(24, 10, 30) },
  { id: 'r2n5ce', title: "Replies to this week's DMs", persona: 'communaute', messages: 6, created_at: D(24, 14), updated_at: D(24, 15) },
  { id: 't8h4yj', title: null, persona: 'redaction', messages: 2, created_at: D(23, 16), updated_at: D(23, 16, 5) },
  { id: 'c5vb2n', title: 'Calm Barrier Cream launch post', persona: 'redaction', messages: 10, created_at: D(22, 9), updated_at: D(22, 11) },
  { id: 'd7xw4k', title: 'Shipping time question', persona: 'communaute', messages: 4, created_at: D(22, 14), updated_at: D(22, 14, 20) },
  { id: 'f3gm9p', title: 'What to test next week', persona: 'analyse', messages: 4, created_at: D(21, 10), updated_at: D(21, 10, 30) },
  { id: 'h6jq8s', title: 'Warmer caption rewrite', persona: 'redaction', messages: 6, created_at: D(20, 15), updated_at: D(20, 15, 40) },
  { id: 'n2ra5u', title: 'Zero-reach day on 28 Sep', persona: 'analyse', messages: 4, created_at: D(20, 9), updated_at: D(20, 9, 25) },
  { id: 'w9ze3y', title: 'Follow-up for a worried customer', persona: 'communaute', messages: 4, created_at: D(20, 8), updated_at: D(20, 8, 15) },
];

const PAIRS = [
  ['Write an Instagram caption for the Hydra Glow Serum launch', 'Here is a draft: "Thirsty skin? Hydra Glow Serum hydrates skin for up to 8 hours."'],
  ['Make it shorter', 'Shorter: "Hydrates skin for up to 8 hours. Simple as that."'],
  ['Add a gentle call to action', 'Added: "Tell us how your skin feels by tonight."'],
  ['Give me a version for Stories', 'For Stories: "Morning ritual: one serum, a full day of comfort."'],
  ['What hashtags fit the brand voice?', 'Warm and simple: #SereinStudio #HydraGlow #SkinCareRoutine'],
  ['Check the claim wording again', 'Only the approved claim C01 is used. No medical promises were added.'],
  ['Thank you, this is perfect', 'Glad it helps. These are drafts for you to review. Nothing was sent or published.'],
];
/** Display-ready items for a saved sample session; k7f2qa has a persona divider after the 4th message. */
export function sampleItems(meta) {
  const items = [];
  const pairs = Math.floor(meta.messages / 2);
  const base = Date.parse(meta.created_at);
  for (let i = 0; i < pairs; i++) {
    const [q, a] = PAIRS[i % PAIRS.length];
    const at = new Date(base + i * 240000).toISOString();
    items.push({ kind: 'user', n: i + 1, text: i === 0 && meta.persona === 'analyse' ? "Summarise last week's engagement" : q, at });
    items.push({ kind: 'assistant', text: a, persona: meta.persona, usage: i % 3 === 2 ? null : { prompt_tokens: 180 + i * 30, output_tokens: 60 + i * 9, latency_ms: 2600 + i * 120, server_duration_ms: 2400 + i * 100 }, tools: [], at: new Date(base + i * 240000 + 5000).toISOString() });
    if (meta.id === 'k7f2qa' && i === 3) items.push({ kind: 'event', text: 'Persona changed to Rédaction' });
  }
  return items;
}
