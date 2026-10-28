// Documents view: the folder the model searches. Add files, see their status, remove, reindex, preview a search.
import { h } from '../dom.js';
import { chip } from '../components/chip.js';
import { button, iconButton } from '../components/button.js';
import { copyButton } from '../components/copy-button.js';
import { emptyState } from '../components/state.js';
import { toast } from '../components/toast.js';
import { viewShell, section } from '../components/view.js';
import { formatBytes } from '../format.js';
import { announce } from '../a11y.js';
import { t } from '../i18n.js';

const TYPES = ['.md', '.txt'];
const POLL_MS = 3000;
const extOf = (name) => name.slice(name.lastIndexOf('.')).toLowerCase();
const TONE = { ready: 'sage', indexing: 'amber', unavailable: 'rose', empty: undefined, off: undefined };

export function mount(root, { api }) {
  let state = { state: 'empty', folder: '', embed_model: 'nomic-embed-text', pending: 0, error: null, items: [], limits: { file_mb: 2, total_mb: 20, types: TYPES } };
  let timer = null, gone = false;
  const status = h('div', { class: 'row' });
  const help = h('p', { class: 'muted' });
  const folder = h('p', { class: 'muted mono' });
  const notice = h('div', { class: 'stack' });
  const err = h('p', { class: 'field__error', role: 'alert', hidden: true });
  const list = h('div');
  const picker = h('input', { type: 'file', multiple: true, accept: TYPES.join(','), class: 'sr-only', tabindex: '-1', 'aria-hidden': 'true' });
  const add = button(t('documents.add'), { variant: 'primary', icon: 'upload' });
  const drop = h('div', { class: 'dropzone' }, add, h('span', { class: 'muted' }, t('documents.drop')), picker);
  const reindex = button(t('documents.reindex'), { icon: 'refresh' });
  const input = h('input', { class: 'input', type: 'search', id: 'doc-q', placeholder: t('documents.placeholder'), autocomplete: 'off' });
  const results = h('div', { class: 'stack', 'aria-live': 'polite' });

  const fail = (message) => { err.textContent = message; err.hidden = false; };
  const clear = () => { err.hidden = true; };

  function render(d) {
    state = { ...state, ...d };
    const n = state.pending;
    status.replaceChildren(chip(t(`documents.state.${state.state}`, { n }), { tone: TONE[state.state] }),
      chip(state.embed_model, { outline: true, mono: true }), h('span', { class: 'grow' }), reindex);
    help.textContent = t('documents.help', { file: state.limits.file_mb, total: state.limits.total_mb });
    folder.textContent = state.folder ? t('documents.folder', { dir: state.folder }) : '';
    notice.replaceChildren(...(state.state === 'unavailable' ? [h('div', { class: 'stack' }, h('p', { class: 'field__error' }, state.error || ''),
      h('p', null, t('documents.unavailable', { model: state.embed_model }), ' ', h('code', null, `ollama pull ${state.embed_model}`),
        copyButton(() => `ollama pull ${state.embed_model}`, { label: t('common.copyCommand') })))]
      : state.state === 'off' ? [h('p', { class: 'muted' }, t('documents.offBody'))] : []));
    reindex.disabled = state.state === 'off';
    add.disabled = state.state === 'off';
    list.replaceChildren(state.items.length ? table(state.items) : emptyState({ icon: 'folder', title: t('documents.state.empty'), body: t('documents.emptyBody', { dir: state.folder || 'data/docs' }), h: 'h3' }));
  }

  function table(items) {
    return h('div', { class: 'table-wrap' }, h('table', { class: 'table table--cards' },
      h('thead', null, h('tr', null, [t('documents.col.name'), t('documents.version'), t('documents.product'), t('documents.chunks'), t('documents.col.state'), ''].map((c, i) => h('th', { scope: 'col', class: i === 3 ? 'num' : '' }, c)))),
      h('tbody', null, items.map((d) => h('tr', null,
        h('td', { 'data-label': t('documents.col.name') }, h('code', { class: 'chip chip--mono' }, d.name), ' ', h('span', { class: 'muted num' }, formatBytes(d.bytes))),
        h('td', { 'data-label': t('documents.version') }, d.version || t('common.na')),
        h('td', { 'data-label': t('documents.product') }, d.product || t('common.na')),
        h('td', { class: 'num', 'data-label': t('documents.chunks') }, d.chunks ?? t('common.na')),
        h('td', { 'data-label': t('documents.col.state') }, chip(t(d.state === 'ready' ? 'documents.ready' : 'documents.pending'), { tone: d.state === 'ready' ? 'sage' : 'amber', outline: true })),
        h('td', null, removeButton(d.name)))))));
  }

  function removeButton(name) {
    let armed = false, timer2 = null;
    const remove = iconButton('trash', t('documents.remove', { name }), { variant: 'ghost', size: 'sm' });
    const sure = button(t('documents.sure'), { variant: 'danger', size: 'sm', hidden: true });
    const disarm = () => { armed = false; sure.hidden = true; remove.hidden = false; clearTimeout(timer2); };
    remove.addEventListener('click', () => { armed = true; remove.hidden = true; sure.hidden = false; sure.focus(); timer2 = setTimeout(disarm, 4000); });
    sure.addEventListener('click', async () => {
      if (!armed) return;
      clearTimeout(timer2);
      try { render(await api.deleteDoc(name)); clear(); toast(t('documents.removed', { name })); announce(t('documents.removed', { name })); } catch (e) { disarm(); fail(e.message); }
    });
    return h('span', { class: 'row' }, remove, sure);
  }

  async function addFiles(files) {
    clear();
    for (const file of files) {
      if (!TYPES.includes(extOf(file.name))) { fail(t('documents.badType', { name: file.name, types: TYPES.join(', ') })); continue; }
      if (file.size > state.limits.file_mb * 1048576) { fail(t('documents.tooBig', { name: file.name, mb: state.limits.file_mb })); continue; }
      let text;
      try { text = new TextDecoder('utf-8', { fatal: true }).decode(await file.arrayBuffer()); } catch { fail(t('documents.notText', { name: file.name })); continue; }
      try { render(await api.putDoc(file.name, text)); toast(t('documents.added', { name: file.name })); announce(t('documents.added', { name: file.name })); } catch (e) { fail(`${file.name}: ${e.message}`); }
    }
  }

  let searchSeq = 0, debounce = null;
  async function search() {
    const q = input.value.trim(), mine = ++searchSeq;
    if (!q) return results.replaceChildren();
    results.replaceChildren(h('p', { class: 'muted' }, t('documents.searching')));
    try {
      const r = await api.searchDocs(q);
      if (mine !== searchSeq || gone) return;
      results.replaceChildren(...(r.items.length ? [h('p', { class: 'muted' }, t('documents.noModel')), ...r.items.map((c) => h('article', { class: 'card stack' },
        h('div', { class: 'row' }, h('code', null, c.source), chip(t('documents.score', { s: Number(c.score).toFixed(2) }), { tone: 'teal' })), h('p', null, c.text)))] : [h('p', { class: 'muted' }, t('documents.notIn'))]));
    } catch (e) { if (mine === searchSeq && !gone) results.replaceChildren(h('p', { class: 'field__error', role: 'alert' }, e.message)); }
  }

  async function refresh() {
    try { render(await api.docs()); } catch (e) { if (!gone) fail(e.message); }
    if (!gone) timer = setTimeout(refresh, POLL_MS);
  }

  add.addEventListener('click', () => picker.click());
  picker.addEventListener('change', () => { addFiles([...picker.files]); picker.value = ''; });
  drop.addEventListener('dragover', (e) => { e.preventDefault(); drop.classList.add('dropzone--over'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('dropzone--over'));
  drop.addEventListener('drop', (e) => { e.preventDefault(); drop.classList.remove('dropzone--over'); addFiles([...e.dataTransfer.files]); });
  reindex.addEventListener('click', async () => {
    clear(); reindex.disabled = true;
    try { const d = await api.reindexDocs(); render(d); toast(t('documents.reindexed', { n: d.documents })); } catch (e) { fail(e.message); }
    reindex.disabled = state.state === 'off';
  });
  input.addEventListener('input', () => { clearTimeout(debounce); debounce = setTimeout(search, 300); });

  root.append(viewShell('documents',
    h('div', { class: 'stack' }, status, help, folder, notice),
    section(t('documents.title'), drop, err, list),
    section(t('documents.search'), h('label', { class: 'sr-only', for: 'doc-q' }, t('documents.search')), input, results)));
  render(state);
  refresh();
  return () => { gone = true; clearTimeout(timer); clearTimeout(debounce); };
}
