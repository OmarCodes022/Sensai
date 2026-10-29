// Approval preview rendering: pre-sanitised lines, visible escape chips, 160 character cut (spec 6.9).
import { h } from '../dom.js';
import { visibleEscapes } from '../safetext.js';
import { t } from '../i18n.js';

const TOKEN = /\\x[0-9a-fA-F]{2}|\\u[0-9a-fA-F]{4}|\\U[0-9a-fA-F]{8}|[\s\S]/gu;
export const CUT = 160;

const escChip = (esc) => {
  const cp = parseInt(esc.slice(2), 16);
  return h('span', { class: 'chip chip--rose chip--mono chip--sq', title: t('esc.hidden', { esc }) }, `U+${cp.toString(16).toUpperCase().padStart(4, '0')}`);
};

/** One line as nodes. Backend escapes such as \x1b become chips; raw control characters too. Returns { node, cut }. */
export function lineNode(text, max = CUT) {
  const frag = document.createDocumentFragment();
  let used = 0, plain = '', cut = false;
  const flush = () => { if (plain) { frag.append(visibleEscapes(plain)); plain = ''; } };
  for (const m of text.matchAll(TOKEN)) {
    const tok = m[0];
    if (used + tok.length > max) { cut = true; break; }
    used += tok.length;
    if (tok.length > 1 && tok[0] === '\\') { flush(); frag.append(escChip(tok)); } else plain += tok;
  }
  flush();
  if (cut) frag.append('…');
  return { node: frag, cut };
}

/** Groups consecutive lines by header: [{header, lines:[text]}]. A line without header continues the group. */
export function groupLines(lines) {
  const groups = [];
  for (const l of lines) {
    const g = groups[groups.length - 1];
    if (g && (!l.header || l.header === g.header)) g.lines.push(l.text);
    else groups.push({ header: l.header || '', lines: [l.text] });
  }
  return groups;
}

/** Collapsed preview: at most 6 lines per argument. Returns { el, incomplete, hidden }. */
export function previewView(preview, { expanded = false, full = null } = {}) {
  const groups = groupLines(full || preview.lines || []);
  let hidden = preview.hidden_lines || 0, anyCut = false;
  const el = h('div', { class: 'stack approval__preview' });
  for (const g of groups) {
    const shown = expanded ? g.lines : g.lines.slice(0, 6);
    if (!expanded) hidden += g.lines.length - shown.length;
    const pre = h('pre', { class: 'code', tabindex: '0' });
    shown.forEach((ln, i) => { const r = lineNode(ln, expanded ? Infinity : CUT); anyCut ||= r.cut; pre.append(r.node, i < shown.length - 1 ? '\n' : ''); });
    el.append(h('div', { class: 'stack approval__arg' }, g.header ? h('span', { class: 'approval__arghead mono' }, g.header) : null, pre));
  }
  if (!expanded && hidden > 0) el.append(h('p', { class: 'approval__more mono' }, t(hidden === 1 ? 'approval.moreOne' : 'approval.more', { n: hidden })));
  return { el, incomplete: !expanded && (preview.incomplete || hidden > 0 || anyCut), hidden };
}
