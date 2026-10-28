// Invisible and bidi control characters become visible chips in code/tool output, stripped from titles.
// Covers C0/C1 controls, soft hyphen, ALM, CGJ, Mongolian vowel separator, zero-width and bidi controls, line/paragraph
// separators, word joiner family, bidi isolates, Hangul fillers, variation selectors, BOM and Unicode tag characters.
const BASE = '\\u0000-\\u0008\\u000B\\u000C\\u000E-\\u001F\\u007F-\\u009F\\u00AD\\u034F\\u061C\\u115F\\u1160\\u180E\\u200B-\\u200F\\u2028\\u2029\\u202A-\\u202E\\u2060-\\u2064\\u2066-\\u2069\\u3164\\uFE00-\\uFE0F\\uFEFF\\u{E0000}-\\u{E007F}';
const INVISIBLE = new RegExp(`[${BASE}]`, 'gu');
const INVISIBLE_CODE = new RegExp(`[${BASE}\\u00A0]`, 'gu');

/** Removes invisible characters (for titles and prose). U+00A0 stays: it is a normal space in prose. */
export const stripInvisible = (s) => String(s ?? '').replace(INVISIBLE, '').trim();

/** Returns a DocumentFragment: plain text with escape chips (U+202E in a rose pill). NBSP is a chip too (code, approvals, tool output). */
export function visibleEscapes(text, { nbsp = true } = {}) {
  const frag = document.createDocumentFragment();
  const re = nbsp ? INVISIBLE_CODE : INVISIBLE;
  const s = String(text ?? '');
  let last = 0;
  for (const m of s.matchAll(re)) {
    if (m.index > last) frag.append(s.slice(last, m.index));
    const chip = document.createElement('span');
    chip.className = 'chip chip--rose chip--mono chip--sq';
    chip.textContent = `U+${m[0].codePointAt(0).toString(16).toUpperCase().padStart(4, '0')}`;
    chip.title = 'Hidden character shown visibly';
    frag.append(chip);
    last = m.index + m[0].length;
  }
  if (last < s.length) frag.append(s.slice(last));
  return frag;
}
