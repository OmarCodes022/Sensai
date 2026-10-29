import { h } from '../dom.js';
import { button, iconButton } from '../components/button.js';
import { openPopover } from '../components/popover.js';
import { openModal, openDrawer, confirmDialog } from '../components/modal.js';
import { toast } from '../components/toast.js';

export const overlays = [
  { title: 'Tooltip', caption: 'Any element with data-tip. Shows after 400 ms on hover and instantly on keyboard focus; Esc dismisses; hoverable (WCAG 1.4.13).',
    build: () => h('div', { class: 'row' }, iconButton('info', 'Tooltip on an icon button'), button('Hover or focus me', { 'data-tip': 'Tooltips explain, they never hide critical actions.' })) },
  { title: 'Popover', caption: 'openPopover(anchor, content, {menu, label}). Anchored, flips, focus moves in, Esc and outside click close and return focus to the anchor.',
    build: () => { const b = button('Open popover', { 'aria-haspopup': 'dialog', 'aria-expanded': 'false' }); b.addEventListener('click', () => openPopover(b, h('div', { class: 'stack' }, h('strong', null, 'Popover'), h('p', null, 'Anchored content.'), button('Action', { size: 'sm' })), { label: 'Demo popover' })); return b; } },
  { title: 'Modal, confirm, drawer', caption: 'Native <dialog>: focus trap, Esc, scroll lock, focus returns to the trigger. confirmDialog focuses the cancel action by default. Drawer sides: left, right, bottom.',
    build: () => h('div', { class: 'row' },
      button('Modal', { onClick: () => openModal({ title: 'Modal title', body: h('p', null, 'Modal body.'), actions: [{ label: 'Close' }] }) }),
      button('Confirm', { onClick: () => confirmDialog({ title: 'Replace profile?', message: 'Keys not in the new JSON are removed.', confirmLabel: 'Replace', danger: true }) }),
      ['left', 'right', 'bottom'].map((s) => button(`Drawer ${s}`, { onClick: () => openDrawer({ side: s, title: `Drawer ${s}`, body: h('p', null, 'Drawer content.') }) }))) },
  { title: 'Toast', caption: 'toast(text, {tone, action}). role=status, max 3 stacked, identical text deduped, auto-dismiss 5 s, pauses on hover and focus.',
    build: () => h('div', { class: 'row' }, button('Toast', { onClick: () => toast('Session ID copied') }), button('With action', { onClick: () => toast('Persona: Analyse. Earlier messages are kept.', { action: { label: 'Undo', onClick: () => {} } }) }), button('Error', { onClick: () => toast('Could not save', { tone: 'rose' }) })) },
];
