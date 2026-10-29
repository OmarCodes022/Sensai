// Calendar panel (week grid or list) and the hidden print document (report figures + week grid on one page).
import { h } from '../../dom.js';
import { chip } from '../../components/chip.js';
import { segmented } from '../../components/form.js';
import { DAYS, ENTRIES, REPORT } from '../../mock/planned-campaign.js';
import { formatNumber, formatPercent } from '../../format.js';
import { t } from '../../i18n.js';

const entryCard = (e) => h('div', { class: 'cal__entry' }, h('span', { class: 'num' }, e.time), h('b', { class: 'mono' }, e.post), h('span', { class: 'muted' }, `Instagram · ${e.theme}`), chip(t('campaign.proposal'), { tone: 'amber' }));
export const grid = () => h('div', { class: 'cal', role: 'list' }, DAYS.map((d, i) => {
  const es = ENTRIES.filter((e) => e.day === i);
  return h('div', { class: `cal__day ${es.length ? '' : 'is-empty'}`, role: 'listitem' }, h('div', { class: 'cal__name' }, d), ...es.map(entryCard));
}));

export function calendarPanel() {
  const body = h('div');
  const list = () => h('ul', { class: 'stack' }, ENTRIES.map((e) => h('li', { class: 'card ribbon row' }, h('b', null, DAYS[e.day]), entryCard(e))));
  const show = (v) => body.replaceChildren(v === 'list' ? list() : grid());
  show('grid');
  return h('div', { class: 'stack', 'data-print-section': 'calendar' }, segmented(t('campaign.view'), [['grid', t('campaign.grid')], ['list', t('campaign.list')]], 'grid', show), body,
    h('p', { class: 'muted' }, t('campaign.notScheduled')), h('p', { class: 'muted' }, t('campaign.noDrag')));
}

export function printDoc() {
  const r = REPORT;
  return h('section', { class: 'print-doc', 'aria-hidden': 'true' }, h('h1', null, t('nav.campaign')), h('p', null, `2026-W44 · ${r.period} · ${r.tz}`),
    h('table', { class: 'table' }, h('tbody', null, [[t('campaign.reached'), formatNumber(r.reached)], [t('campaign.engaged'), formatNumber(r.engaged)], [t('campaign.rate'), formatPercent(r.rate)]].map((x) => h('tr', null, h('th', null, x[0]), h('td', null, x[1]))))),
    h('p', null, t('campaign.formula'), ' ', r.formula), h('h2', null, t('campaign.tab.calendar')), grid(), h('p', null, t('campaign.notScheduled')), h('p', null, t('preview.notice')));
}
