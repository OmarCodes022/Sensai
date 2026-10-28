// Settings view (spec 8.4): effective config, UI preferences, backend card.
import { h } from '../dom.js';
import { chip } from '../components/chip.js';
import { viewShell, section } from '../components/view.js';
import { configList } from '../settings/config-rows.js';
import { prefsForm } from '../settings/prefs-form.js';
import { formatDuration } from '../format.js';
import { t } from '../i18n.js';

export const CAPABILITIES = ['chat', 'personas', 'sessions', 'profile', 'usage', 'tools', 'approval', 'sandbox', 'run_script', 'history', 'guardrails', 'facts', 'documents', 'context_budget', 'campaign', 'weekly_run', 'export', 'share', 'web_search', 'mcp', 'think', 'team', 'ask_user', 'file_access', 'cache', 'examples', 'prompt_versions', 'branching', 'stats', 'schedule', 'evaluation'];

function backendCard(store) {
  const { health, mock } = store.get().status, caps = store.get().capabilities || {};
  const on = CAPABILITIES.filter((c) => caps[c]).length;
  return h('div', { class: 'card stack' },
    h('dl', { class: 'kv' }, h('dt', null, t('settings.version')), h('dd', { class: 'mono' }, health?.version ?? t('common.na')),
      h('dt', null, t('settings.uptime')), h('dd', null, health?.uptime_s != null ? formatDuration(health.uptime_s * 1000) : t('common.na')),
      h('dt', null, t('settings.mode')), h('dd', null, mock ? t('common.mockData') : t('settings.live'))),
    h('p', { class: 'muted' }, t('settings.capCount', { on, total: CAPABILITIES.length })),
    h('ul', { class: 'row caps', 'aria-label': t('settings.caps') }, CAPABILITIES.map((c) => h('li', null, chip(`${caps[c] ? t('settings.capOn') : t('settings.capOff')}: ${c}`, { tone: caps[c] ? 'sage' : undefined, icon: caps[c] ? 'check' : null, mono: true })))));
}

export function mount(root, { store, actions }) {
  const cfg = h('div'), back = h('div');
  root.append(viewShell('settings', section(t('settings.effective'), cfg), section(t('settings.prefs'), prefsForm({ store, actions })), section(t('settings.backend'), back)));
  const paint = () => { cfg.replaceChildren(configList(store.get().config)); back.replaceChildren(backendCard(store)); };
  paint();
  return store.subscribe(paint, ['config', 'capabilities', 'status']);
}
