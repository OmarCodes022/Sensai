import { h } from '../dom.js';
import { icon } from '../icons.js';
import { t } from '../i18n.js';

/** Modal built on native <dialog>: focus trap, Esc, scroll lock and focus return come for free. */
export function openModal({ title, body, actions = [], wide = false, top = false, dismissible = true, className = '', label }) {
  const prev = document.activeElement;
  const close = () => { if (dlg.open) dlg.close(); };
  const head = h('div', { class: 'modal__head' }, h('h2', { id: 'modal-title' }, title || ''), dismissible ? h('button', { type: 'button', class: 'btn btn--ghost btn--icon btn--sm', 'aria-label': t('common.close'), onclick: close }, icon('x', { size: 16 })) : null);
  const foot = actions.length ? h('div', { class: 'modal__foot' }, actions.map((a) => h('button', { type: 'button', class: `btn ${a.variant ? `btn--${a.variant}` : ''}`, onclick: () => a.onClick ? a.onClick(close) : close() }, a.label))) : null;
  const dlg = h('dialog', { class: `modal ${wide ? 'modal--wide' : ''} ${top ? 'modal--top' : ''} ${className}`, 'aria-labelledby': title ? 'modal-title' : null, 'aria-label': title ? null : label }, title ? head : null, h('div', { class: 'modal__body' }, body), foot);
  if (!dismissible) dlg.addEventListener('cancel', (e) => e.preventDefault());
  dlg.addEventListener('click', (e) => { if (dismissible && e.target === dlg) close(); });
  dlg.addEventListener('close', () => { dlg.remove(); if (prev?.isConnected) prev.focus(); });
  document.body.append(dlg);
  dlg.showModal();
  return { dialog: dlg, close };
}

/** Promise<boolean>. The cancel action is the default focus. */
export function confirmDialog({ title, message, confirmLabel = t('common.confirm'), cancelLabel = t('common.cancel'), danger = false }) {
  return new Promise((resolve) => {
    let result = false;
    const m = openModal({
      title, body: h('p', null, message),
      actions: [
        { label: cancelLabel, onClick: (c) => c() },
        { label: confirmLabel, variant: danger ? 'danger' : 'primary', onClick: (c) => { result = true; c(); } },
      ],
    });
    m.dialog.addEventListener('close', () => resolve(result));
    m.dialog.querySelector('.modal__foot .btn')?.focus();
  });
}

/** Drawer: a side-anchored dialog. side: left | right | bottom. */
export function openDrawer({ side = 'right', title, body }) {
  return openModal({ title, body, className: `drawer drawer--${side}` });
}
