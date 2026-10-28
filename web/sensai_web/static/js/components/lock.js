import { h } from '../dom.js';
import { openModal } from './modal.js';
import { t } from '../i18n.js';

/** Full-page, non-dismissible single-tab lock (409). */
export function showLock(api, actions) {
  const note = h('p', { class: 'muted', role: 'status' });
  const m = openModal({
    title: t('lock.title'), dismissible: false, className: 'lock',
    body: [h('p', null, t('lock.body')), note],
    actions: [
      { label: t('common.close'), onClick: () => { window.close(); note.textContent = t('lock.closeHint'); } },
      { label: t('lock.takeover'), variant: 'primary', onClick: async (close) => {
        try { await api.takeover(); actions.setStatus({ locked: false }); close(); } catch (e) { note.textContent = e.message; }
      } },
    ],
  });
  return m;
}
