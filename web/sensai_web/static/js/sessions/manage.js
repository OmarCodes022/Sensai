// Rename, export and delete for one saved session (buttons in the sessions detail panel).
import { h } from '../dom.js';
import { button } from '../components/button.js';
import { field, input } from '../components/form.js';
import { openModal, confirmDialog } from '../components/modal.js';
import { toast } from '../components/toast.js';
import { announce } from '../a11y.js';
import { t } from '../i18n.js';

function download(filename, text) {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/markdown;charset=utf-8' }));
  const a = h('a', { href: url, download: filename });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** done(kind) runs after a rename or delete so the view refreshes. */
export function sessionButtons({ api, store, session, done }) {
  const say = (m) => { toast(m); announce(m); };
  const fail = (e) => toast(e.message, { tone: 'rose' });

  function rename() {
    const box = input({ value: /\(branch\)$/.test(session.title) || session.title === '(sans titre)' ? '' : session.title, maxlength: 100, autocomplete: 'off' });
    const err = h('p', { class: 'field__error', role: 'alert', hidden: true });
    const m = openModal({ title: t('sessions.renameTitle'), body: h('form', { class: 'stack', onsubmit: (e) => e.preventDefault() }, field(t('sessions.titleField'), box), err), actions: [
      { label: t('common.cancel'), onClick: (c) => c() },
      { label: t('common.save'), variant: 'primary', onClick: async (close) => {
        try {
          const { title } = await api.renameSession(session.id, box.value);
          const cur = store.get().session;
          if (cur?.id === session.id) store.set({ session: { ...cur, title } });
          close(); say(t('sessions.renamed')); done('rename', title);
        } catch (e) { err.textContent = e.message; err.hidden = false; }
      } }] });
    box.focus(); box.select();
    box.addEventListener('keydown', (e) => { if (e.key === 'Enter') m.dialog.querySelector('.modal__foot .btn--primary')?.click(); });
  }

  async function exportIt() {
    try { const { filename, markdown } = await api.exportSession(session.id); download(filename, markdown); say(t('sessions.exported', { name: filename })); } catch (e) { fail(e); }
  }

  async function remove() {
    if (!(await confirmDialog({ title: t('sessions.deleteTitle'), message: t('sessions.deleteBody'), confirmLabel: t('sessions.delete'), danger: true }))) return;
    try { await api.deleteSession(session.id); say(t('sessions.deleted')); done('delete'); } catch (e) { fail(e); }
  }

  return h('div', { class: 'row' }, button(t('sessions.rename'), { icon: 'edit', onClick: rename }), button(t('sessions.export'), { icon: 'download', onClick: exportIt }),
    button(t('sessions.delete'), { variant: 'danger', icon: 'trash', onClick: remove }));
}
