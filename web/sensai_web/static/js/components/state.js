import { h } from '../dom.js';
import { icon } from '../icons.js';
import { button } from './button.js';
import { skeleton } from './meter.js';
import { t } from '../i18n.js';

/** Empty/error state: icon, title, body, optional actions [{label, onClick, variant}]. */
export function emptyState({ icon: ic = 'info', title, body, actions = [], tone, h: level = 'h2' }) {
  return h('div', { class: `empty ${tone === 'error' ? 'empty--error' : ''}`, role: tone === 'error' ? 'alert' : null },
    h('span', { class: 'empty__icon' }, icon(ic, { size: 24 })), h(level, null, title), body ? h('p', null, body) : null,
    actions.length ? h('div', { class: 'row' }, actions.map((a) => button(a.label, { variant: a.variant || 'secondary', onClick: a.onClick }))) : null);
}

export const errorState = ({ title, body, onRetry }) => emptyState({ icon: 'alert-triangle', tone: 'error', title, body, actions: onRetry ? [{ label: t('common.retry'), onClick: onRetry }] : [] });

export const skeletonRows = (n = 6) => h('div', { class: 'stack', 'aria-busy': 'true', 'aria-label': t('common.loading') }, Array.from({ length: n }, () => h('div', { class: 'stack' }, skeleton('70%'), skeleton('40%'))));
