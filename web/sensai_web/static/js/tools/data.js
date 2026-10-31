// Sandbox data folder: see the files, add some (picker or drop), remove one, or start from example data.
import { h } from '../dom.js';
import { button, iconButton } from '../components/button.js';
import { toast } from '../components/toast.js';
import { formatBytes } from '../format.js';
import { announce } from '../a11y.js';
import { openModal } from '../components/modal.js';
import { t } from '../i18n.js';

const TYPES = ['.csv', '.tsv', '.json', '.txt', '.md'];
const extOf = (name) => name.slice(name.lastIndexOf('.')).toLowerCase();

export function createDataCard({ api }) {
  let state = { dir: '', exists: false, files: [], limits: { file_mb: 10, total_mb: 50, types: TYPES } };
  const help = h('p', { class: 'muted' });
  const path = h('p', { class: 'muted mono' });
  const empty = h('p', { class: 'muted' });
  const list = h('ul', { class: 'datafiles' });
  const err = h('p', { class: 'field__error', role: 'alert', hidden: true });
  const picker = h('input', { type: 'file', multiple: true, accept: TYPES.join(','), class: 'sr-only', tabindex: '-1', 'aria-hidden': 'true' });
  const add = button(t('tools.dataAdd'), { variant: 'primary', icon: 'upload' });
  const example = button(t('tools.dataExample'), { icon: 'file-text' });
  const drop = h('div', { class: 'dropzone' }, add, h('span', { class: 'muted' }, t('tools.dataDrop')), picker);
  const el = h('div', { class: 'stack' }, help, path, drop, h('div', { class: 'row' }, example, h('span', { class: 'muted' }, t('tools.dataExampleHelp'))), err, empty, list);

  const fail = (message) => { err.textContent = message; err.hidden = false; };
  const clear = () => { err.hidden = true; };

  function render(d) {
    state = { ...state, ...d };
    help.textContent = t('tools.dataHelp', { file: state.limits.file_mb, total: state.limits.total_mb });
    path.textContent = t('tools.dataDir', { dir: state.dir });
    empty.textContent = state.files.length ? '' : t(state.exists ? 'tools.dataEmpty' : 'tools.dataFolderNew');
    empty.hidden = state.files.length > 0;
    list.replaceChildren(...state.files.map((f) => row(f)));
    example.disabled = state.files.some((f) => f.name === 'engagement.csv');
  }

  function row(file) {
    let armed = false, timer = null;
    const remove = iconButton('trash', t('tools.dataDelete', { name: file.name }), { variant: 'ghost', size: 'sm' });
    const sure = button(t('tools.dataSure'), { variant: 'danger', size: 'sm', hidden: true });
    const disarm = () => { armed = false; sure.hidden = true; remove.hidden = false; clearTimeout(timer); };
    remove.addEventListener('click', () => { armed = true; remove.hidden = true; sure.hidden = false; sure.focus(); timer = setTimeout(disarm, 4000); });
    sure.addEventListener('click', async () => {
      if (!armed) return;
      clearTimeout(timer);
      try { render(await api.deleteData(file.name)); clear(); toast(t('tools.dataRemoved', { name: file.name })); announce(t('tools.dataRemoved', { name: file.name })); }
      catch (e) { disarm(); fail(e.message); }
    });
    const view = h('button', { type: 'button', class: 'link-btn mono', onclick: () => preview(file.name) }, file.name);
    return h('li', { class: 'datafiles__row' }, view, h('span', { class: 'muted num' }, formatBytes(file.bytes)), h('span', { class: 'grow' }), remove, sure);
  }

  async function preview(name) {
    try {
      const { text } = await api.readData(name);
      openModal({ title: name, wide: true, body: h('pre', { class: 'code', tabindex: '0' }, text || t('tools.dataBlank')), actions: [{ label: t('common.close'), onClick: (c) => c() }] });
    } catch (e) { fail(e.message); }
  }

  async function addFiles(files) {
    clear();
    for (const file of files) {
      if (!TYPES.includes(extOf(file.name))) { fail(t('tools.dataBadType', { name: file.name, types: TYPES.join(', ') })); continue; }
      if (file.size > state.limits.file_mb * 1048576) { fail(t('tools.dataTooBig', { name: file.name, mb: state.limits.file_mb })); continue; }
      let text;
      try { text = new TextDecoder('utf-8', { fatal: true }).decode(await file.arrayBuffer()); } catch { fail(t('tools.dataNotText', { name: file.name })); continue; }
      try { render(await api.putData(file.name, text)); toast(t('tools.dataAdded', { name: file.name })); announce(t('tools.dataAdded', { name: file.name })); }
      catch (e) { fail(`${file.name}: ${e.message}`); }
    }
  }

  add.addEventListener('click', () => picker.click());
  picker.addEventListener('change', () => { addFiles([...picker.files]); picker.value = ''; });
  drop.addEventListener('dragover', (e) => { e.preventDefault(); drop.classList.add('dropzone--over'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('dropzone--over'));
  drop.addEventListener('drop', (e) => { e.preventDefault(); drop.classList.remove('dropzone--over'); addFiles([...e.dataTransfer.files]); });
  example.addEventListener('click', async () => {
    clear();
    try { render(await api.exampleData()); toast(t('tools.dataAdded', { name: 'engagement.csv' })); } catch (e) { fail(e.message); }
  });

  api.runData().then(render).catch((e) => fail(e.message));
  render(state);
  return { el };
}
