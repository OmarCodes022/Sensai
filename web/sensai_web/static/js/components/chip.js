import { h } from '../dom.js';
import { icon } from '../icons.js';
import { t } from '../i18n.js';

/** chip(text, {tone: accent|sage|amber|rose|teal|plum, icon, mono, outline, onRemove}) */
export function chip(text, { tone, icon: ic, mono, outline, onRemove, title } = {}) {
  const c = h('span', { class: ['chip', tone && `chip--${tone}`, mono && 'chip--mono', outline && 'chip--outline'].filter(Boolean).join(' '), title }, ic ? icon(ic, { size: 12 }) : null, text);
  if (onRemove) c.append(h('button', { type: 'button', 'aria-label': t('common.remove', { name: text }), onclick: onRemove }, icon('x', { size: 12 })));
  return c;
}

export const plannedChip = (taskId) => chip([t('common.planned'), taskId ? ` ${taskId}` : ''].join(''), { outline: true });

export const statusDot = (tone) => h('span', { class: `dot ${tone ? `dot--${tone}` : ''}`, 'aria-hidden': 'true' });
