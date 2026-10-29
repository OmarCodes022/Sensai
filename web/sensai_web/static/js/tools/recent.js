// Recent tool calls of the current session, built from the stored session items (no extra endpoint).
import { h } from '../dom.js';
import { chip } from '../components/chip.js';
import { formatDuration, formatClock } from '../format.js';
import { hrefFor } from '../router.js';
import { attemptOf } from '../chat/tool-card.js';
import { t } from '../i18n.js';

const status = (c) => (c.refused ? 'refused' : c.ok === null || c.ok === undefined ? 'cancelled' : c.ok ? 'ok' : attemptOf(c)?.stopped ? 'stopped' : c.meta?.timed_out ? 'timeout' : 'error');
const TONE = { ok: 'sage', error: 'rose', timeout: 'rose', refused: 'amber', cancelled: 'amber', stopped: 'rose' };

export function recentCalls(session) {
  const calls = [];
  for (const it of session?.items || []) {
    if (it.kind === 'assistant') for (const c of it.tools || []) calls.push({ ...c, at: it.at });
    else if (it.kind === 'tool') calls.push(it);
  }
  if (!calls.length) return h('p', { class: 'muted' }, t('tools.recentNone'));
  return h('div', { class: 'table-wrap' }, h('table', { class: 'table table--cards' }, h('caption', { class: 'sr-only' }, t('tools.recent')),
    h('thead', null, h('tr', null, ['time', 'tool', 'status', 'duration', 'message'].map((k) => h('th', { scope: 'col' }, t(`tools.col.${k}`))))),
    h('tbody', null, calls.reverse().map((c) => h('tr', null,
      h('td', { 'data-label': t('tools.col.time') }, c.at ? formatClock(c.at) : t('common.na')),
      h('td', { 'data-label': t('tools.col.tool') }, h('code', { class: 'chip chip--mono' }, c.name)),
      h('td', { 'data-label': t('tools.col.status') }, chip(t(`tool.status.${status(c)}`), { tone: TONE[status(c)] })),
      h('td', { class: 'num', 'data-label': t('tools.col.duration') }, formatDuration(c.duration_ms)),
      h('td', { 'data-label': t('tools.col.message') }, h('a', { href: hrefFor('chat', session.id) }, t('tools.openChat'))))))));
}
