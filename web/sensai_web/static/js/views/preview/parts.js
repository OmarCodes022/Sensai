// Small shared pieces for preview modules.
import { h } from '../../dom.js';
import { t } from '../../i18n.js';

export const note = () => h('p', { class: 'muted' }, t('preview.notice'));
/** Card with a MOCK corner ribbon. */
export const mockCard = (...kids) => h('div', { class: 'card ribbon stack' }, ...kids);
export const stat = (label, value) => h('div', { class: 'card ribbon stat' }, h('span', { class: 'stat__value num' }, value), h('span', { class: 'stat__label' }, label));
export function table(head, rows) {
  return h('div', { class: 'table-wrap' }, h('table', { class: 'table table--cards' }, h('thead', null, h('tr', null, head.map((x) => h('th', { scope: 'col' }, x)))),
    h('tbody', null, rows.map((r) => h('tr', null, r.map((c, i) => h('td', { 'data-label': head[i], class: typeof c === 'number' ? 'num' : '' }, c)))))));
}
