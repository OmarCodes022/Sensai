// Pure profile validation: must be a JSON object of strings. Errors carry a 1-based line number.
const lineAt = (text, pos) => text.slice(0, pos).split('\n').length;

/** Returns { value } on success or { errors: [{line, key, args}] } where key is a strings.* suffix. */
export function validateProfile(text) {
  if (!text.trim()) return { errors: [{ line: 1, key: 'empty' }] };
  let value;
  try { value = JSON.parse(text); }
  catch (e) {
    const m = /position (\d+)/.exec(e.message), lc = /line (\d+) column/.exec(e.message);
    const line = m ? lineAt(text, Number(m[1])) : lc ? Number(lc[1]) : 1;
    return { errors: [{ line, key: 'syntax', args: { detail: e.message } }] };
  }
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return { errors: [{ line: 1, key: 'notObject' }] };
  const errors = [];
  const lines = text.split('\n');
  for (const [k, v] of Object.entries(value)) {
    if (typeof v === 'string') continue;
    const idx = lines.findIndex((l) => l.includes(JSON.stringify(k)));
    errors.push({ line: idx < 0 ? 1 : idx + 1, key: 'notString', args: { name: k } });
  }
  return errors.length ? { errors } : { value };
}
