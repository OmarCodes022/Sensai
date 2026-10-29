// Report panel: figures table, formula, interpretation, daily bar chart (SVG) with a table alternative, edge cases.
import { h } from '../../dom.js';
import { icon } from '../../icons.js';
import { REPORT, DAILY } from '../../mock/planned-campaign.js';
import { formatNumber, formatPercent } from '../../format.js';
import { t } from '../../i18n.js';

const NS = 'http://www.w3.org/2000/svg';
const svg = (tag, attrs, text) => { const e = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v); if (text) e.textContent = text; return e; };

/** rate(): n/a for zero reach, never 0 percent. */
export const rate = (reached, engaged) => (!reached ? null : (engaged / reached) * 100);

function chart() {
  const W = 480, H = 160, bw = 36, max = Math.max(...DAILY.map((d) => d[1]));
  const s = svg('svg', { viewBox: `0 0 ${W} ${H + 24}`, role: 'img', 'aria-label': t('campaign.chartLabel'), class: 'chart' });
  DAILY.forEach(([day, reach], i) => {
    const x = 12 + i * 58, bh = max ? (reach / max) * H : 0;
    s.append(svg('rect', { x, y: H - bh, width: bw, height: Math.max(bh, reach ? 1 : 0), rx: 3, class: reach ? 'chart__bar' : 'chart__zero' }));
    if (!reach) s.append(svg('path', { d: `M${x} ${H - 2}h${bw}`, class: 'chart__flag' }), svg('text', { x: x + bw / 2, y: H - 8, 'text-anchor': 'middle', class: 'chart__txt' }, '!'));
    s.append(svg('text', { x: x + bw / 2, y: H + 16, 'text-anchor': 'middle', class: 'chart__txt' }, day.split(' ')[0]));
  });
  return s;
}

export function reportPanel() {
  const r = REPORT, pct = rate(r.reached, r.engaged);
  const table = (rows, head) => h('div', { class: 'table-wrap' }, h('table', { class: 'table' }, h('thead', null, h('tr', null, head.map((x) => h('th', { scope: 'col' }, x)))), h('tbody', null, rows.map((row) => h('tr', null, row.map((c, i) => h('td', { class: i ? 'num' : '' }, c)))))));
  return h('div', { class: 'stack', 'data-print-section': 'report' },
    table([[t('campaign.period'), r.period], [t('campaign.tz'), r.tz], [t('campaign.source'), h('code', null, r.source)], [t('campaign.reached'), formatNumber(r.reached)], [t('campaign.engaged'), formatNumber(r.engaged)], [t('campaign.rate'), formatPercent(pct)]], [t('campaign.figure'), t('campaign.value')]),
    h('p', { class: 'muted' }, t('campaign.formula'), ' ', h('code', null, r.formula)),
    h('blockquote', { class: 'interp card card--flat' }, h('strong', null, t('campaign.interp')), h('p', null, r.note)),
    h('div', { class: 'card ribbon stack' }, h('h3', null, t('campaign.daily')), chart(),
      h('details', null, h('summary', null, t('campaign.tableAlt')), table(DAILY.map(([d, a, e]) => [d, formatNumber(a), formatNumber(e), a ? formatPercent(rate(a, e)) : h('span', { class: 'na-zero' }, t('campaign.zeroReach'))]), [t('campaign.day'), t('campaign.reached'), t('campaign.engaged'), t('campaign.rate')])),
      h('p', { class: 'muted' }, icon('alert-triangle', { size: 14 }), ' ', t('campaign.flag28'))),
    h('details', { class: 'card' }, h('summary', null, t('campaign.edgeTitle')), h('ul', { class: 'bullets' }, ['zero', 'invalid', 'missing'].map((k) => h('li', { class: k === 'zero' ? '' : 'field__error' }, t(`campaign.edge.${k}`))))));
}
