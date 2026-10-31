// "Effective configuration" list (spec 8.4): value plus source chip. Secret-looking keys are never rendered.
import { h } from '../dom.js';
import { chip } from '../components/chip.js';
import { t } from '../i18n.js';

export const KEYS = ['ollama_host', 'model', 'request_timeout', 'turn_budget', 'context_length', 'database_path', 'creator', 'profile_file', 'data_dir', 'prompt_file', 'personas_file', 'docs_dir', 'embed_model'];
export const SECRET = /token|key|secret|password/i;
const SOURCES = ['cli', 'env', 'dotenv', 'default'];
const DEFAULT_TEXT = { prompt_file: 'settings.packaged', personas_file: 'settings.builtin', profile_file: 'settings.none' };

/** Builds the list from config.effective, falling back to the few flat fields every backend reports. */
export function effectiveRows(config) {
  const eff = config?.effective || {};
  const flat = { model: config?.model, context_length: config?.context_length, creator: config?.creator, turn_budget: config?.limits?.turn_seconds };
  return KEYS.map((k) => ({ key: k, value: eff[k] ? eff[k].value : flat[k], source: eff[k]?.source || null }));
}

export function renderValue(r) {
  if (SECRET.test(r.key)) return h('em', null, t('settings.hidden'));
  if (r.value === null || r.value === undefined) return DEFAULT_TEXT[r.key] && r.source ? t(DEFAULT_TEXT[r.key]) : t('common.na');
  const unit = r.key === 'request_timeout' || r.key === 'turn_budget' ? ' s' : '';
  return h('span', { class: 'mono' }, `${r.value}${unit}`);
}

export function configList(config) {
  const rows = effectiveRows(config);
  return h('div', { class: 'stack' }, h('dl', { class: 'kv kv--wide' }, rows.flatMap((r) => [
    h('dt', null, t(`settings.k.${r.key}`)),
    h('dd', { class: 'row' }, renderValue(r), r.source ? chip(SOURCES.includes(r.source) ? t(`settings.src.${r.source}`) : r.source, { outline: true, title: t('settings.source') }) : chip(t('settings.sourceNa'), { outline: true }),
      r.key === 'data_dir' ? h('span', { class: 'muted' }, t('settings.dataNote')) : null)])),
    config?.effective ? null : h('p', { class: 'muted' }, t('settings.noSources')));
}
