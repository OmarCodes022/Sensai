// Safe Markdown renderer. Builds DOM nodes only: no innerHTML, raw HTML stays literal text.
import { codeBlock } from './components/code-block.js';
import { stripInvisible } from './safetext.js';
import { t } from './i18n.js';

const SAFE_URL = /^(https?:|mailto:)/i;
const el = (tag, cls) => { const e = document.createElement(tag); if (cls) e.className = cls; return e; };

export const safeUrl = (u) => SAFE_URL.test(u.trim().replace(/[\u0000- ]/g, '')) ? u.trim() : null;

function link(text, url, opts) {
  const href = safeUrl(url);
  if (!href) return document.createTextNode(`[${text}](${url})`);
  const a = el('a', 'md-link');
  a.href = href;
  a.rel = 'noopener noreferrer';
  a.dataset.url = href; // confirm-before-open is handled by a delegated click handler
  a.title = href;
  if (opts.plain) a.append(text); else inline(text, a, { ...opts, inLink: true });
  return a;
}

const INLINE = new RegExp([
  '(`+)([\\s\\S]*?[^`])\\1(?!`)',                 // 1,2 code
  '\\*\\*(?=\\S)([\\s\\S]*?\\S)\\*\\*',            // 3 bold
  '(?<![\\w*])\\*(?=\\S)([^*]*?\\S)\\*(?![\\w*])', // 4 italic *
  '(?<![\\w_])_(?=\\S)([^_]*?\\S)_(?![\\w_])',     // 5 italic _
  '!\\[([^\\]]*)\\]\\(([^)\\s]*)\\)',               // 6,7 image
  '\\[([^\\]]+)\\]\\(([^)\\s]+)\\)',                // 8,9 link
  '(https?:\\/\\/[^\\s<>()\\[\\]]+[^\\s<>()\\[\\].,;:!?])', // 10 autolink
  '\\[(\\d{1,2})\\]',                              // 11 citation
].join('|'), 'g');

/** Appends inline nodes for src into parent. opts.sources enables [n] citation buttons. */
const BIDI = /[\u202A-\u202E\u2066-\u2069]/g; // bidi overrides are dropped from prose (kept visible in code)
function inline(raw, parent, opts = {}) {
  const src = raw.replace(BIDI, '');
  let last = 0;
  for (const m of src.matchAll(INLINE)) {
    if (m.index > last) parent.append(src.slice(last, m.index));
    last = m.index + m[0].length;
    if (m[2] !== undefined) { const c = el('code'); c.textContent = m[2]; parent.append(c); }
    else if (m[3] !== undefined) { const b = el('strong'); inline(m[3], b, opts); parent.append(b); }
    else if (m[4] !== undefined || m[5] !== undefined) { const i = el('em'); inline(m[4] ?? m[5], i, opts); parent.append(i); }
    else if (m[7] !== undefined) {
      parent.append(m[0]);
      const note = el('span', 'md-note muted'); note.textContent = ` (${t('md.imageHidden')})`; parent.append(note);
    } else if (m[9] !== undefined) parent.append(link(m[8], m[9], opts));
    else if (m[10] !== undefined) parent.append(link(m[10], m[10], { ...opts, plain: true }));
    else if (m[11] !== undefined) {
      const n = Number(m[11]);
      if (opts.sources?.some((s) => s.n === n)) {
        const b = el('button', 'md-cite'); b.type = 'button'; b.dataset.cite = String(n);
        b.setAttribute('aria-label', t('md.source', { n }));
        const sup = el('sup'); sup.textContent = String(n); b.append(sup); parent.append(b);
      } else parent.append(m[0]);
    }
  }
  if (last < src.length) parent.append(src.slice(last));
}

function inlineLines(text, parent, opts) {
  text.split('\n').forEach((line, i) => { if (i) parent.append(el('br')); inline(line, parent, opts); });
}

const LIST = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/;
const closeVirtual = (src) => {
  // Streaming: close unfinished constructs so partial text renders sensibly.
  let s = src;
  if ((s.match(/^\s*```/gm) || []).length % 2) s += '\n```';
  return s;
};
const closeInline = (line) => {
  let s = line;
  if ((s.match(/`/g) || []).length % 2) s += '`';
  if ((s.match(/\*\*/g) || []).length % 2) s += '**';
  return s;
};

function buildList(items, opts) {
  const root = el(items[0].ordered ? 'ol' : 'ul');
  const stack = [{ indent: items[0].indent, list: root, lastLi: null }];
  for (const it of items) {
    let top = stack[stack.length - 1];
    if (it.indent > top.indent && top.lastLi && stack.length < 3) {
      const list = el(it.ordered ? 'ol' : 'ul');
      top.lastLi.append(list);
      stack.push(top = { indent: it.indent, list, lastLi: null });
    } else while (it.indent < top.indent && stack.length > 1) top = stack[(stack.pop(), stack.length - 1)];
    const li = el('li');
    inline(it.text, li, opts);
    top.list.append(li);
    top.lastLi = li;
  }
  return root;
}

const cells = (row) => row.trim().replace(/^\||\|$/g, '').split('|').map((c) => c.trim());
const isDelim = (row) => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(row);

function buildTable(lines, opts) {
  const wrap = el('div', 'table-wrap md-table');
  const table = el('table', 'table');
  const aligns = cells(lines[1]).map((c) => (c.startsWith(':') && c.endsWith(':') ? 'center' : c.endsWith(':') ? 'right' : 'left'));
  const mk = (tag, row) => {
    const tr = el('tr');
    cells(row).forEach((c, i) => { const cell = el(tag); cell.style.setProperty('text-align', aligns[i] || 'left'); inline(c, cell, opts); tr.append(cell); });
    return tr;
  };
  const thead = el('thead'); thead.append(mk('th', lines[0]));
  const tbody = el('tbody'); lines.slice(2).forEach((r) => tbody.append(mk('td', r)));
  table.append(thead, tbody); wrap.append(table);
  return wrap;
}

/** Renders Markdown to a DocumentFragment. opts: { streaming, sources }. */
export function renderMarkdown(src, opts = {}) {
  const frag = document.createDocumentFragment();
  const text = opts.streaming ? closeVirtual(src.replace(/\r\n?/g, '\n')) : src.replace(/\r\n?/g, '\n');
  const lines = text.split('\n');
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    let m;
    if (!line.trim()) { i++; continue; }
    if ((m = line.match(/^\s*```\s*([\w+-]*)/))) {
      const body = [];
      for (i++; i < lines.length && !/^\s*```\s*$/.test(lines[i]); i++) body.push(lines[i]);
      i++;
      frag.append(codeBlock(body.join('\n'), m[1]));
    } else if ((m = line.match(/^(#{1,4})\s+(.*)$/))) {
      const h = el(`h${Math.min(m[1].length + 2, 5)}`); inline(m[2], h, opts); frag.append(h); i++;
    } else if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) { frag.append(el('hr')); i++; }
    else if (/^\s*>/.test(line)) {
      const body = [];
      for (; i < lines.length && /^\s*>/.test(lines[i]); i++) body.push(lines[i].replace(/^\s*>\s?/, ''));
      const q = el('blockquote'); q.append(renderMarkdown(body.join('\n'), opts)); frag.append(q);
    } else if (line.includes('|') && i + 1 < lines.length && isDelim(lines[i + 1])) {
      const rows = [line, lines[i + 1]];
      for (i += 2; i < lines.length && lines[i].includes('|') && lines[i].trim(); i++) rows.push(lines[i]);
      frag.append(buildTable(rows, opts));
    } else if (LIST.test(line)) {
      const items = [];
      for (; i < lines.length; i++) {
        const lm = lines[i].match(LIST);
        if (lm) items.push({ indent: lm[1].replace(/\t/g, '    ').length, ordered: /\d/.test(lm[2]), text: lm[3] });
        else if (lines[i].trim() && /^\s{2,}\S/.test(lines[i]) && items.length) items[items.length - 1].text += ` ${lines[i].trim()}`;
        else break;
      }
      frag.append(buildList(items, opts));
    } else {
      const body = [];
      for (; i < lines.length && lines[i].trim() && !/^\s*(```|#{1,4}\s|>)/.test(lines[i]) && !LIST.test(lines[i]); i++) body.push(lines[i]);
      const p = el('p');
      inlineLines(opts.streaming ? closeInline(body.join('\n')) : body.join('\n'), p, opts);
      frag.append(p);
    }
  }
  return frag;
}

/** Replaces container content. Callers coalesce streaming calls with requestAnimationFrame. */
export function renderInto(container, src, opts) {
  container.replaceChildren(renderMarkdown(src, opts));
  container.setAttribute('dir', 'auto');
}

export const plainTitle = stripInvisible;
