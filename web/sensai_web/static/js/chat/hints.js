// Composer helpers: privacy pattern check and the chips shown under the textarea.
import { h } from '../dom.js';
import { icon } from '../icons.js';
import { formatNumber } from '../format.js';
import { t } from '../i18n.js';

const EMAIL = /[\w.+-]+@[\w-]+(\.[\w-]+)+/;
const PHONE = /(?<![\w.])\+?\d[\d\s().-]{7,}\d(?![\w])/;
const HANDLE = /(?<![\w@.])@[A-Za-z0-9_.]{2,}/;
export const LARGE_PASTE = 20000;

export const looksPersonal = (text) => EMAIL.test(text) || PHONE.test(text) || HANDLE.test(text);

export function privacyChip(guardrails) {
  return h('span', { class: 'chip chip--plum chip--wrap', role: 'note' }, icon('eye-off', { size: 12 }), guardrails ? t('hint.privacyGuarded') : t('hint.privacy'));
}

export function pasteChip(count, onUndo) {
  const chip = h('span', { class: 'chip chip--amber', role: 'status' }, icon('info', { size: 12 }), t('hint.largePaste', { n: formatNumber(count) }),
    h('button', { type: 'button', class: 'link-btn', onclick: () => { onUndo(); chip.remove(); } }, t('hint.undo')));
  return chip;
}
