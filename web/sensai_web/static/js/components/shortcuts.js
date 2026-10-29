import { h } from '../dom.js';
import { openModal } from './modal.js';
import { kbd } from './meter.js';
import { modKey } from '../platform.js';
import { t } from '../i18n.js';

export const SHORTCUTS = (m) => [
  ['Enter', 'send'], ['Shift+Enter', 'newline'], ['Esc', 'stop'], ['Up', 'recall'],
  [`${m}+K`, 'palette'], [`${m}+Shift+O`, 'newChat'], [`${m}+B`, 'sidebar'], [`${m}+.`, 'inspector'],
  [`${m}+/`, 'shortcuts'], ['/', 'searchSidebar'], ['y / n / v', 'approval'], ['Alt+1..6', 'views'], [`${m}+Shift+L`, 'theme'],
];

export function openShortcuts() {
  const dl = h('dl', { class: 'shortcuts' });
  for (const [keys, id] of SHORTCUTS(modKey())) {
    dl.append(h('dt', null, t(`shortcuts.${id}`)), h('dd', null, keys.split('+').flatMap((k, i) => (i ? ['+', ...kbd(k)] : kbd(k)))));
  }
  return openModal({ title: t('shortcuts.title'), body: dl, wide: true, actions: [{ label: t('common.close') }] });
}
