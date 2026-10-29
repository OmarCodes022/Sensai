// Status popovers: Ollama connection, model, remote. Shared by the top bar and the narrow "Status" button.
import { h } from '../dom.js';
import { copyButton } from './copy-button.js';
import { statusDot } from './chip.js';
import { formatDuration } from '../format.js';
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

export function modelPanel(status) {
  const m = status.health?.model;
  const name = m?.name || t('common.na');
  return h('div', { class: 'stack' }, h('div', { class: 'row' }, statusDot(m?.available ? 'sage' : m ? 'rose' : null), h('strong', { class: 'mono' }, name)),
    h('p', null, m ? (m.available ? t('status.modelAvailable') : t('status.modelMissing')) : t('status.modelUnknown')),
    m && !m.available ? hint(`ollama pull ${name}`) : null, h('p', { class: 'muted' }, t('status.modelFixed')));
}

export function allPanel(status) {
  return h('div', { class: 'stack' }, ollamaPanel(status), h('hr', { class: 'divider' }), modelPanel(status),
    status.health?.remote ? h('p', null, t('status.remote')) : null);
}
