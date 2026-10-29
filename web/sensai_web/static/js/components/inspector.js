import { h } from '../dom.js';
import { tabs } from './tabs.js';
import { meter } from './meter.js';
import { chip } from './chip.js';
import { emptyState } from './state.js';
import { formatNumber, formatTokens, formatDuration } from '../format.js';
import { t } from '../i18n.js';

export function createInspector({ store, api }) {
  const body = (render) => { const box = h('div', { class: 'stack' }); render(box); return box; };

  const turnPanel = () => body((box) => {
    const turn = store.get().selectedTurn;
    if (!turn) return box.append(emptyState({ icon: 'info', title: t('inspector.noTurn'), body: t('inspector.noTurnBody') }));
    box.append(h('dl', { class: 'kv' }, h('dt', null, t('usage.tokens')), h('dd', null, formatTokens(turn.prompt_tokens, turn.output_tokens)),
      h('dt', null, t('usage.latency')), h('dd', null, formatDuration(turn.latency_ms)), h('dt', null, t('usage.server')), h('dd', null, formatDuration(turn.server_duration_ms))));
  });

  const contextPanel = () => body((box) => {
    const s = store.get(), sess = s.session, persona = s.personas.find((p) => p.id === s.activePersona);
    box.append(h('h3', null, t('inspector.persona')), persona ? h('div', { class: 'stack' }, h('strong', null, persona.name, ' ', h('code', { class: 'chip chip--mono' }, persona.id)), h('p', { class: 'muted' }, persona.role)) : h('p', { class: 'muted' }, t('persona.none')));
    const u = sess?.usage || {};
    box.append(h('h3', null, t('inspector.usage')),
      h('dl', { class: 'kv' }, h('dt', null, t('usage.turns')), h('dd', { class: 'num' }, formatNumber(u.turns ?? 0)), h('dt', null, t('usage.tokens')), h('dd', null, formatTokens(u.prompt_tokens, u.output_tokens))));
    const max = s.config?.context_length;
    const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null);
    const prompt = num(u.last_prompt_tokens) ?? num(u.prompt_tokens), out = num(u.output_tokens);
    const used = prompt != null ? prompt + (out ?? 0) : null;
    box.append(h('h3', null, t('inspector.contextMeter')), max && used != null ? meter({ value: used, max, marker: !!s.capabilities.context_budget }) : h('p', { class: 'muted' }, t('inspector.meterUnknown')),
      max && used != null && out == null ? h('p', { class: 'muted' }, t('inspector.meterPartial')) : null);
  });

  const toolsPanel = () => body((box) => {
    box.append(h('span', { class: 'skeleton', 'aria-hidden': 'true' }));
    api.tools().then(({ items }) => {
      box.replaceChildren(...(items.length ? items.map((x) => h('div', { class: 'card stack' }, h('div', { class: 'row' }, h('code', { class: 'chip chip--mono' }, x.name), x.confirm ? chip(t('tools.confirm'), { tone: 'amber' }) : null), h('p', { class: 'muted' }, x.description))) : [emptyState({ icon: 'tools', title: t('tools.none') })]));
    }).catch(() => box.replaceChildren(h('p', { class: 'muted' }, t('tools.loadError'))));
  });

  const sourcesPanel = () => emptyState({ icon: 'database', title: t('inspector.sources'), body: t('inspector.sourcesBody') });

  const root = h('aside', { class: 'inspector', 'aria-label': t('inspector.title') });
  const mountTabs = (selected) => {
    root.replaceChildren(tabs({ label: t('inspector.title'), selected, items: [
      { id: 'turn', label: t('inspector.turn'), render: turnPanel }, { id: 'context', label: t('inspector.context'), render: contextPanel },
      { id: 'tools', label: t('inspector.tools'), render: toolsPanel }, { id: 'sources', label: t('inspector.sources'), render: sourcesPanel }] }));
  };
  mountTabs('turn');
  const current = () => root.querySelector('[role=tab][aria-selected=true]')?.dataset.id;
  store.subscribe(() => mountTabs(current()), ['selectedTurn', 'session', 'activePersona', 'config']);
  document.addEventListener('sensai:lang', () => mountTabs(current()));
  root.select = (id) => root.firstElementChild.select(id);
  return root;
}
