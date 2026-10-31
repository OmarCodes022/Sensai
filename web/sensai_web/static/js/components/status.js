// Status popovers: Ollama connection, model, remote. Shared by the top bar and the narrow "Status" button.
import { h } from '../dom.js';
import { copyButton } from './copy-button.js';
import { statusDot } from './chip.js';
import { formatDuration } from '../format.js';
import { button } from './button.js';
import { select } from './form.js';
import { t } from '../i18n.js';

export function ollamaState(status) {
  const hl = status.health;
  if (status.backend === 'checking') return { tone: 'amber', text: t('status.checking') };
  if (hl?.ollama?.reachable) return { tone: 'sage', text: t('status.ollamaReady') };
  return { tone: 'rose', text: t('status.cannotReach', { host: hl?.ollama?.host || 'localhost:11434' }) };
}

const hint = (cmd) => h('div', { class: 'row' }, h('code', { class: 'chip chip--mono' }, cmd), copyButton(() => cmd, { label: t('common.copyCommand') }));

export function ollamaPanel(status) {
  const s = ollamaState(status), o = status.health?.ollama;
  return h('div', { class: 'stack' }, h('div', { class: 'row' }, statusDot(s.tone), h('strong', null, s.text)),
    h('dl', { class: 'kv' }, h('dt', null, t('status.host')), h('dd', { class: 'mono' }, o?.host || t('common.na')), h('dt', null, t('status.latency')), h('dd', null, formatDuration(o?.latency_ms))),
    o?.reachable ? null : hint('ollama serve'));
}

/** The model in use, and (given api and actions) a picker over the models Ollama has installed. */
export function modelPanel(status, { api, actions } = {}) {
  const m = status.health?.model;
  const name = m?.name || t('common.na');
  const picker = h('div', { class: 'stack' });
  if (api) api.models().then(({ installed, current }) => {
    if (!installed.length) return;
    const sel = select(installed.map((n) => [n, n]), { 'aria-label': t('status.pickModel'), class: 'select mono' });
    sel.value = installed.includes(current) ? current : (installed.find((n) => n.split(':')[0] === current) || installed[0]);
    const use = button(t('status.useModel'), { variant: 'primary', size: 'sm', onClick: async () => { use.disabled = true; try { await actions.setModel(sel.value); } finally { use.disabled = false; } } });
    picker.replaceChildren(h('div', { class: 'row' }, sel, use), h('p', { class: 'muted' }, t('status.modelNote')));
  }).catch(() => {});
  return h('div', { class: 'stack' }, h('div', { class: 'row' }, statusDot(m?.available ? 'sage' : m ? 'rose' : null), h('strong', { class: 'mono' }, name)),
    h('p', null, m ? (m.available ? t('status.modelAvailable') : t('status.modelMissing')) : t('status.modelUnknown')),
    m && !m.available ? hint(`ollama pull ${name}`) : null, picker);
}

export function allPanel(status, tools) {
  return h('div', { class: 'stack' }, ollamaPanel(status), h('hr', { class: 'divider' }), modelPanel(status, tools),
    status.health?.remote ? h('p', null, t('status.remote')) : null);
}
