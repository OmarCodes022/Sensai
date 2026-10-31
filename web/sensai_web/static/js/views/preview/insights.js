// Insights preview (spec 9.3 / T33): stat tiles, per-day table and sparklines with table alternatives.
import { h } from '../../dom.js';
import { select, field } from '../../components/form.js';
import { STATS, PER_DAY, TOOL_USE, KINDS } from '../../mock/planned-misc.js';
import { formatNumber, formatPercent, formatDuration, formatTokens } from '../../format.js';
import { note, stat, table, mockCard } from './parts.js';
import { t } from '../../i18n.js';

const NS = 'http://www.w3.org/2000/svg';
export function sparkline(values, label) {
  const max = Math.max(...values, 1), W = 160, H = 36;
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * W},${H - (v / max) * (H - 4) - 2}`).join(' ');
  const s = document.createElementNS(NS, 'svg');
  for (const [k, v] of Object.entries({ viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': label, class: 'spark' })) s.setAttribute(k, v);
  const pl = document.createElementNS(NS, 'polyline');
  pl.setAttribute('points', pts); pl.setAttribute('class', 'spark__line');
  s.append(pl);
  return s;
}

export function mountPreview(root) {
  const kind = select([['', t('insights.allKinds')], ...KINDS.map((k) => [k, k])]);
  const rate = STATS.calls ? (STATS.errors / STATS.calls) * 100 : null;
  root.replaceChildren(h('div', { class: 'stack' }, note(), field(t('insights.kind'), kind, { help: t('insights.kindHelp') }),
    h('div', { class: 'stats' }, stat(t('insights.calls'), formatNumber(STATS.calls)), stat(t('insights.errors'), `${formatNumber(STATS.errors)} (${formatPercent(rate)})`),
      stat(t('insights.latency'), formatDuration(STATS.latencyMs)), stat(t('insights.tokens'), formatTokens(STATS.promptTokens, STATS.outputTokens))),
    mockCard(h('h3', null, t('insights.perDay')), h('div', { class: 'row' }, sparkline(PER_DAY.map((d) => d[1]), t('insights.sparkCalls')), sparkline(PER_DAY.map((d) => d[3]), t('insights.sparkLatency'))),
      table([t('insights.day'), t('insights.calls'), t('insights.errors'), t('insights.latency')], PER_DAY.map(([d, c, e, l]) => [d, c, e, formatDuration(l)]))),
    mockCard(h('h3', null, t('insights.toolUse')), table([t('tools.col.tool'), t('insights.calls'), t('insights.failures')], TOOL_USE.map(([n, c, f]) => [h('code', null, n), c, f]))),
    h('p', { class: 'muted' }, t('insights.plain'))));
}
