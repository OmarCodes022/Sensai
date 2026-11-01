// Insights (EV3): usage statistics from the local log: calls, errors, latency, tokens, tools, one row per day.
import { h } from '../dom.js';
import { chip } from '../components/chip.js';
import { emptyState } from '../components/state.js';
import { viewShell } from '../components/view.js';
import { formatNumber, formatPercent, formatDuration, formatTokens } from '../format.js';
import { table } from './preview/parts.js';
import { sparkline } from './preview/insights.js';
import { t } from '../i18n.js';

// Real figures: no "mock" ribbon, unlike the preview's tiles.
const stat = (label, value) => h('div', { class: 'card stat' }, h('span', { class: 'stat__value num' }, value), h('span', { class: 'stat__label' }, label));

export function mount(root, { api }) {
  const body = h('div', { class: 'stack' }, h('span', { class: 'skeleton', 'aria-hidden': 'true' }));
  root.append(viewShell('insights', body));
  api.stats().then((s) => {
    if (!s.calls) return body.replaceChildren(emptyState({ icon: 'chart', title: t('insights.empty'), body: s.file ? t('insights.emptyBody', { file: s.file }) : t('insights.off') }));
    const days = s.days.length > 1 ? h('div', { class: 'row' }, sparkline(s.days.map((d) => d.calls), t('insights.sparkCalls')), sparkline(s.days.map((d) => d.avg_latency_ms || 0), t('insights.sparkLatency'))) : null;
    const tools = Object.entries(s.tools);
    body.replaceChildren(
      h('div', { class: 'stats' }, stat(t('insights.calls'), formatNumber(s.calls)), stat(t('insights.errors'), `${formatNumber(s.errors)} (${formatPercent(s.error_rate)})`),
        stat(t('insights.latency'), formatDuration(s.avg_latency_ms)), stat(t('insights.tokens'), formatTokens(s.prompt_tokens, s.output_tokens))),
      h('div', { class: 'row' }, Object.entries(s.kinds).map(([k, n]) => chip(`${k} ${n}`, { outline: true })), s.cancelled ? chip(t('insights.cancelled', { n: s.cancelled }), { tone: 'amber' }) : null),
      h('section', { class: 'stack' }, h('h2', null, t('insights.perDay')), days,
        table([t('insights.day'), t('insights.calls'), t('insights.errors'), t('insights.latency')], s.days.map((d) => [d.day, d.calls, d.errors, formatDuration(d.avg_latency_ms)]))),
      h('section', { class: 'stack' }, h('h2', null, t('insights.toolUse')),
        tools.length ? table([t('tools.col.tool'), t('insights.calls'), t('insights.failures')], tools.map(([n, v]) => [h('code', null, n), v.calls, v.failed])) : h('p', { class: 'muted' }, t('insights.noTools'))),
      h('section', { class: 'stack' }, h('h2', null, t('insights.recent')),
        table([t('insights.time'), t('insights.kindCol'), t('insights.question'), t('insights.latency'), t('insights.error')],
          s.recent.map((r) => [r.time.slice(0, 16).replace('T', ' '), r.kind, h('span', { dir: 'auto' }, (r.question || '').slice(0, 80)), formatDuration(r.latency_ms), r.error || '']))),
      h('p', { class: 'muted' }, t('insights.plain'), ' ', h('code', null, s.file)));
  }).catch((e) => body.replaceChildren(h('p', { class: 'field__error' }, e.message)));
}
