// Tools view (spec 8.3): registry, recent calls, sandbox runner.
import { h } from '../dom.js';
import { chip } from '../components/chip.js';
import { emptyState } from '../components/state.js';
import { viewShell, loadInto, section } from '../components/view.js';
import { recentCalls } from '../tools/recent.js';
import { createSandbox } from '../tools/sandbox.js';
import { formatNumber } from '../format.js';
import { t } from '../i18n.js';

function registry(items) {
  if (!items.length) return emptyState({ icon: 'tools', title: t('tools.none') });
  return h('div', { class: 'table-wrap' }, h('table', { class: 'table table--cards' }, h('caption', { class: 'sr-only' }, t('tools.registry')),
    h('thead', null, h('tr', null, ['name', 'description', 'timeout', 'confirm', 'max'].map((k) => h('th', { scope: 'col', class: k === 'timeout' || k === 'max' ? 'num' : '' }, t(`tools.col.${k}`))))),
    h('tbody', null, items.map((x) => {
      const [server, short] = x.name.includes('.') ? x.name.split('.', 2) : [null, x.name];
      return h('tr', null,
        h('td', { 'data-label': t('tools.col.name') }, server ? chip(server, { tone: 'teal', outline: true }) : null, h('code', { class: 'chip chip--mono' }, server ? short : x.name)),
        h('td', { 'data-label': t('tools.col.description') }, x.description),
        h('td', { class: 'num', 'data-label': t('tools.col.timeout') }, x.timeout != null ? `${formatNumber(x.timeout)} s` : t('common.na')),
        h('td', { 'data-label': t('tools.col.confirm') }, x.confirm ? chip(t('tools.confirm'), { tone: 'amber' }) : chip(t('tools.noConfirm'), { outline: true })),
        h('td', { class: 'num', 'data-label': t('tools.col.max') }, x.max_calls != null ? formatNumber(x.max_calls) : t('tools.noLimit')));
    }))));
}

export function mount(root, { api, store }) {
  const reg = h('div'), recent = h('div');
  const box = createSandbox({ api, store });
  root.append(viewShell('tools', section(t('tools.registry'), reg), section(t('tools.recent'), recent), section(t('tools.sandboxTitle'), box.el)));
  loadInto(reg, () => api.tools(), (d) => reg.replaceChildren(registry(d.items || [])), t('tools.loadError'));
  const paint = () => recent.replaceChildren(recentCalls(store.get().session));
  paint();
  const unsub = store.subscribe(paint, ['session']);
  return () => { unsub(); box.dispose(); };
}
