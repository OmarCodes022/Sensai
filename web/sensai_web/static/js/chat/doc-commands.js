// Slash commands of the documents and data files, run in the page (no model call): /docs, /add, /remove, /reindex and the + button.
import { h } from '../dom.js';
import { chip } from '../components/chip.js';
import { button } from '../components/button.js';
import { toast } from '../components/toast.js';
import { pickFiles, readTextFile } from '../components/uploads.js';
import { announce } from '../a11y.js';
import { t } from '../i18n.js';

const DOC_TYPES = ['.md', '.txt'];
const DATA_TYPES = ['.csv', '.tsv', '.json', '.txt', '.md'];

/** deps: { api, transcript, router }. Returns { docs, add, remove, reindex, attach }. */
export function createDocCommands({ api, transcript, router }) {
  const show = (node) => { transcript.append(node, new Date().toISOString()); transcript.scrollToBottom(); };
  const card = (title, ...kids) => h('section', { class: 'card stack doccmd', role: 'status' }, h('strong', null, title), ...kids);
  const fail = (e) => { show(card(t('doccmd.failed'), h('p', { class: 'field__error', role: 'alert' }, e.message))); };
  const open = () => button(t('doccmd.open'), { variant: 'ghost', size: 'sm', icon: 'folder', onClick: () => router.go('#/documents') });

  function listCard(d, { removable = false } = {}) {
    const rows = d.items.map((x) => h('div', { class: 'row' }, h('code', { class: 'chip chip--mono' }, x.name), h('span', { class: 'muted' }, x.version || ''),
      h('span', { class: 'grow' }), chip(t(x.state === 'ready' ? 'documents.ready' : 'documents.pending'), { tone: x.state === 'ready' ? 'sage' : 'amber', outline: true }),
      removable ? button(t('documents.remove', { name: x.name }), { variant: 'ghost', size: 'sm', icon: 'trash', onClick: () => remove(x.name) }) : null));
    return card(t('doccmd.listTitle', { n: d.items.length }), h('div', { class: 'row' }, chip(t(`documents.state.${d.state}`, { n: d.pending }), { tone: d.state === 'ready' ? 'sage' : d.state === 'unavailable' ? 'rose' : undefined }), h('span', { class: 'grow' }), open()),
      ...(rows.length ? rows : [h('p', { class: 'muted' }, t('doccmd.none'))]));
  }

  async function docs(arg = '') {
    try {
      if (!arg) return show(listCard(await api.docs()));
      const r = await api.searchDocs(arg);
      show(card(t('doccmd.searchTitle', { q: arg }), h('p', { class: 'muted' }, t('documents.noModel')),
        ...(r.items.length ? r.items.map((c) => h('div', { class: 'stack' }, h('div', { class: 'row' }, h('code', null, c.source), chip(t('documents.score', { s: Number(c.score).toFixed(2) }), { tone: 'teal' })), h('p', null, c.text)))
          : [h('p', { class: 'muted' }, t('documents.notIn'))])));
    } catch (e) { fail(e); }
  }

  async function remove(name = '') {
    try {
      if (!name) return show(listCard(await api.docs(), { removable: true }));
      const d = await api.deleteDoc(name);
      toast(t('documents.removed', { name })); announce(t('documents.removed', { name }));
      show(card(t('documents.removed', { name }), h('p', { class: 'muted' }, t('doccmd.left', { n: d.items.length }))));
    } catch (e) { fail(e); }
  }

  async function reindex() {
    try { const d = await api.reindexDocs(); show(card(t('documents.reindexed', { n: d.documents }))); } catch (e) { fail(e); }
  }

  async function upload(files, { types, maxMb, keys, put, title }) {
    const added = [], errors = [];
    for (const file of files) {
      try { await put(file.name, await readTextFile(file, { types, maxMb, keys })); added.push(file.name); } catch (e) { errors.push(e.message); }
    }
    if (!added.length && !errors.length) return;
    if (added.length) { toast(t(title, { n: added.length })); announce(t(title, { n: added.length })); }
    show(card(added.length ? t(title, { n: added.length }) : t('doccmd.failed'), ...added.map((n) => h('code', { class: 'chip chip--mono' }, n)),
      ...errors.map((m) => h('p', { class: 'field__error', role: 'alert' }, m)), added.length ? open() : null));
  }

  async function add() {
    const files = await pickFiles({ accept: DOC_TYPES.join(',') });
    if (!files.length) return;
    let maxMb = 2;
    try { maxMb = (await api.docs()).limits.file_mb; } catch { /* the server checks again */ }
    await upload(files, { types: DOC_TYPES, maxMb, keys: { badType: 'documents.badType', tooBig: 'documents.tooBig', notText: 'documents.notText' }, put: (n, text) => api.putDoc(n, text), title: 'doccmd.addedDocs' });
  }

  async function addData() {
    const files = await pickFiles({ accept: DATA_TYPES.join(',') });
    if (!files.length) return;
    let maxMb = 10;
    try { maxMb = (await api.runData()).limits.file_mb; } catch { /* the server checks again */ }
    await upload(files, { types: DATA_TYPES, maxMb, keys: { badType: 'tools.dataBadType', tooBig: 'tools.dataTooBig', notText: 'tools.dataNotText' }, put: (n, text) => api.putData(n, text), title: 'doccmd.addedData' });
  }

  return { docs, add, remove, reindex, attach: (kind) => (kind === 'data' ? addData() : add()) };
}
