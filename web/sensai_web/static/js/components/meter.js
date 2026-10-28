import { h } from '../dom.js';
import { formatNumber } from '../format.js';
import { t } from '../i18n.js';

/** Context meter with text alternative. sage <60%, amber 60-85, rose above. marker draws the 80% budget line. */
export function meter({ value, max, marker = false }) {
  const pct = max ? Math.min(100, (value / max) * 100) : 0;
  const level = pct > 85 ? 'high' : pct >= 60 ? 'warn' : 'ok';
  const text = t('meter.text', { value: formatNumber(value), max: formatNumber(max), pct: Math.round(pct) });
  const bar = h('div', { class: 'meter__bar', role: 'meter', 'aria-valuemin': 0, 'aria-valuemax': max, 'aria-valuenow': value, 'aria-valuetext': text }, h('span', { class: 'meter__fill', vars: { '--v': `${pct}%` } }), marker ? h('span', { class: 'meter__mark' }) : null);
  return h('div', { class: 'meter', dataset: { level } }, bar, h('span', { class: 'meter__text' }, text));
}

export const progressBar = (pct) => h('div', { class: 'progress', role: 'progressbar', 'aria-valuemin': 0, 'aria-valuemax': 100, 'aria-valuenow': Math.round(pct) }, h('i', { vars: { '--v': `${pct}%` } }));
export const progressRing = (pct, label) => h('span', { class: 'ring', role: 'progressbar', 'aria-label': label, 'aria-valuemin': 0, 'aria-valuemax': 100, 'aria-valuenow': Math.round(pct), vars: { '--v': pct } });
export const spinner = (label) => h('span', { class: 'spinner', role: label ? 'status' : null, 'aria-label': label, 'aria-hidden': label ? null : 'true' });
export const skeleton = (w = '100%') => h('span', { class: 'skeleton', 'aria-hidden': 'true', vars: { width: w } });
export const kbd = (...keys) => keys.map((k) => h('kbd', null, k));
