// Documents preview (spec 9.4): indexed documents, reindex note, embedding model, search with no model call.
import { h } from '../../dom.js';
import { chip } from '../../components/chip.js';
import { button } from '../../components/button.js';
import { DOCS, CHUNKS } from '../../mock/planned-misc.js';
import { note, table, mockCard } from './parts.js';
import { t } from '../../i18n.js';

const words = (s) => s.toLowerCase().match(/[\p{L}\p{N}]+/gu) || [];
/** Word-overlap score in [0, 1] against the query. */
export const score = (q, text) => { const qs = new Set(words(q)); return qs.size ? words(text).filter((w) => qs.has(w)).length / qs.size : 0; };

/** Text with query words wrapped in <mark>, built from DOM nodes only. */
function highlight(text, q) {
  const qs = new Set(words(q));
  const out = [];
  for (const part of text.split(/([\p{L}\p{N}]+)/u)) out.push(qs.has(part.toLowerCase()) ? h('mark', null, part) : part);
  return out;
}

export function mountPreview(root) {
  const results = h('div', { class: 'stack', 'aria-live': 'polite' });
  const input = h('input', { class: 'input', type: 'search', id: 'doc-q', placeholder: t('documents.placeholder') });
  const reindexNote = h('p', { class: 'muted', role: 'status' });
  const search = () => {
    const q = input.value.trim();
    if (!q) return results.replaceChildren();
    const top = CHUNKS.map((c) => ({ ...c, s: score(q, c.text) })).sort((a, b) => b.s - a.s).filter((c) => c.s > 0).slice(0, 3);
    results.replaceChildren(...(top.length ? [h('p', { class: 'muted' }, t('documents.noModel')), ...top.map((c) => h('article', { class: 'card stack' },
      h('div', { class: 'row' }, h('code', null, c.source), chip(c.version, { outline: true }), chip(t('documents.score', { s: c.s.toFixed(2) }), { tone: 'teal' })), h('p', null, highlight(c.text, q))))] : [h('p', { class: 'empty-calm' }, t('documents.notIn'))]));
  };
  input.addEventListener('input', search);
  root.replaceChildren(h('div', { class: 'stack' }, note(),
    mockCard(table([t('documents.source'), t('documents.type'), t('documents.product'), t('documents.version'), t('documents.chunks')], DOCS.map((d) => [h('code', null, d.id), d.type, d.product, d.version, d.chunks])),
      h('div', { class: 'row' }, button(t('documents.reindex'), { icon: 'refresh', onClick: () => { reindexNote.textContent = t('documents.reindexNote'); } }), chip(t('documents.embedOk'), { tone: 'sage', icon: 'check' })), reindexNote,
      h('p', { class: 'muted' }, t('documents.pullHint'), ' ', h('code', null, 'ollama pull nomic-embed-text'))),
    mockCard(h('label', { class: 'field__label', for: 'doc-q' }, t('documents.search')), input, results)));
}
