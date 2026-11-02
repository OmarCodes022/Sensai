// Notes (data/notes/): the files file access reads. Add, open, edit and remove them; the rules decide what the model sees.
import { h } from '../dom.js';
import { button, iconButton } from '../components/button.js';
import { field, input, textarea } from '../components/form.js';
import { openModal } from '../components/modal.js';
import { toast } from '../components/toast.js';
import { formatBytes } from '../format.js';
import { t } from '../i18n.js';

export function createNotesCard({ api }) {
  const dir = h('p', { class: 'muted mono' });
  const list = h('ul', { class: 'datafiles' });
  const err = h('p', { class: 'field__error', role: 'alert', hidden: true });
  const add = button(t('notes.new'), { variant: 'primary', icon: 'plus', onClick: () => editor(null, '') });
  const el = h('div', { class: 'stack' }, h('p', { class: 'muted' }, t('notes.help')), dir, h('div', { class: 'row' }, add), err, list);
  const fail = (e) => { err.textContent = e.message; err.hidden = false; };

  function render(d) {
    err.hidden = true;
    dir.textContent = t('notes.dir', { dir: d.dir });
    list.replaceChildren(...(d.items.length ? d.items.map(row) : [h('li', { class: 'muted' }, t('notes.empty'))]));
  }

  function row(note) {
    const open = h('button', { type: 'button', class: 'link-btn mono', onclick: () => api.readNote(note.path).then((n) => editor(n.path, n.text), fail) }, note.path);
    const remove = iconButton('trash', t('notes.delete', { path: note.path }), { variant: 'ghost', size: 'sm', onClick: async () => {
      try { render(await api.deleteNote(note.path)); toast(t('notes.removed', { path: note.path })); } catch (e) { fail(e); }
    } });
    return h('li', { class: 'datafiles__row' }, open, h('span', { class: 'muted num' }, formatBytes(note.bytes)), h('span', { class: 'grow' }), remove);
  }

  function editor(path, text) {
    const name = input({ class: 'input mono', value: path || '', placeholder: 'launch.md', disabled: path !== null, autocomplete: 'off' });
    const body = textarea({ rows: 14, class: 'textarea mono' });
    body.value = text;
    const problem = h('p', { class: 'field__error', role: 'alert', hidden: true });
    openModal({ title: path || t('notes.new'), wide: true,
      body: h('div', { class: 'stack' }, field(t('notes.path'), name, { help: t('notes.pathHelp') }), field(t('notes.text'), body), problem),
      actions: [{ label: t('common.cancel'), onClick: (c) => c() }, { label: t('notes.save'), variant: 'primary', onClick: async (close) => {
        try { render(await api.putNote(name.value.trim(), body.value)); toast(t('notes.saved', { path: name.value.trim() })); close(); }
        catch (e) { problem.textContent = e.message; problem.hidden = false; }
      } }] });
  }

  api.notes().then(render, fail);
  return { el };
}
