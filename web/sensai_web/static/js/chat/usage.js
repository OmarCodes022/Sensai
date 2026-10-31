// Token and latency chips (spec 6.7). Unknown values read "n/a", never 0.
import { h } from '../dom.js';
import { formatTokens, formatDuration } from '../format.js';
import { t } from '../i18n.js';

const known = (v) => v !== null && v !== undefined;

export function usageTip(u) {
  const parts = [`${t('usage.promptTokens')}: ${known(u?.prompt_tokens) ? u.prompt_tokens : t('common.na')}`, `${t('usage.outputTokens')}: ${known(u?.output_tokens) ? u.output_tokens : t('common.na')}`,
    `${t('usage.latency')}: ${formatDuration(u?.latency_ms)}`];
  if (known(u?.server_duration_ms)) parts.push(`${t('usage.server')}: ${formatDuration(u.server_duration_ms)}`);
  parts.push(known(u?.prompt_tokens) || known(u?.output_tokens) ? t('usage.reported') : t('usage.notReported'));
  return parts.join('. ');
}

/** Returns the chip nodes for a finished assistant message. */
export function usageChips(u) {
  const tip = usageTip(u);
  return [
    h('span', { class: 'chip chip--outline num', tabindex: '0', 'data-tip': tip }, formatTokens(u?.prompt_tokens, u?.output_tokens)),
    h('span', { class: 'chip chip--outline num', tabindex: '0', 'data-tip': tip }, formatDuration(u?.latency_ms)),
  ];
}
