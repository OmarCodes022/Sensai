// Tools view (spec 8.3): MCP status and setup, registry, recent calls, sandbox runner.
import { h } from '../dom.js';
import { button } from '../components/button.js';
import { chip } from '../components/chip.js';
import { emptyState } from '../components/state.js';
import { viewShell, loadInto, section } from '../components/view.js';
import { recentCalls } from '../tools/recent.js';
import { createSandbox } from '../tools/sandbox.js';
import { formatNumber } from '../format.js';
import { t } from '../i18n.js';

/** A known tool's description in the page language; any other tool keeps the text the backend sent. */
const describe = (tool) => { const key = `tool.desc.${tool.name}`; const text = t(key); return text === key ? tool.description : text; };

function registry(items) {
  if (!items.length) return emptyState({ icon: 'tools', title: t('tools.none') });
  return h('div', { class: 'table-wrap' }, h('table', { class: 'table table--cards' }, h('caption', { class: 'sr-only' }, t('tools.registry')),
    h('thead', null, h('tr', null, ['name', 'description', 'timeout', 'confirm', 'max'].map((k) => h('th', { scope: 'col', class: k === 'timeout' || k === 'max' ? 'num' : '' }, t(`tools.col.${k}`))))),
    h('tbody', null, items.map((x) => {
      const dot = x.name.indexOf('.');
      const [server, short] = dot > 0 ? [x.name.slice(0, dot), x.name.slice(dot + 1)] : [null, x.name];
      return h('tr', null,
        h('td', { 'data-label': t('tools.col.name') }, server ? chip(server, { tone: 'teal', outline: true }) : null, h('code', { class: 'chip chip--mono' }, server ? short : x.name)),
        h('td', { 'data-label': t('tools.col.description') }, describe(x)),
        h('td', { class: 'num', 'data-label': t('tools.col.timeout') }, x.timeout != null ? `${formatNumber(x.timeout)} s` : t('common.na')),
        h('td', { 'data-label': t('tools.col.confirm') }, x.confirm ? chip(t('tools.confirm'), { tone: 'amber' }) : chip(t('tools.noConfirm'), { outline: true })),
        h('td', { class: 'num', 'data-label': t('tools.col.max') }, x.max_calls != null ? formatNumber(x.max_calls) : t('tools.noLimit')));
    }))));
}

/** Read-only on purpose: each entry runs a local command, so the user edits the file and this page explains how. */
function mcpPanel(d, onTrust) {
  const servers = d.servers || [];
  return [
    d.untrusted ? h('div', { class: 'stack', role: 'alert' }, h('p', null, t('tools.mcp.untrusted')),
      d.untrusted.folder ? h('p', null, t('tools.mcp.folder', { path: d.untrusted.folder })) : null,
      h('pre', { class: 'code code--wrap', tabindex: '0', dir: 'ltr' }, d.untrusted.commands.join('\n')),
      h('div', { class: 'row' }, button(t('tools.mcp.trust'), { onClick: () => onTrust(d.untrusted.digest) }))) : null,
    d.trust_error ? h('p', { role: 'alert' }, d.trust_error) : null,
    d.config ? h('p', null, t('tools.mcp.config', { path: d.config }), d.found ? '' : ` ${t('tools.mcp.missing')}`) : null,
    d.error ? h('p', { role: 'alert' }, d.error, ' ', t('tools.reloadHint')) : null,
    servers.map((s) => h('p', { role: s.error ? 'alert' : null },
      s.error ? `${s.name}: ${s.error} ${t('tools.reloadHint')}` : `${s.name}: ${t('tools.mcp.count', { n: s.count })}`)),
    h('details', { class: 'card', open: !servers.length && !d.untrusted }, h('summary', null, t('tools.mcp.setup')),
      h('ol', { class: 'steps stack' },
        h('li', null, t('tools.mcp.step1'), d.example ? h('pre', { class: 'code', tabindex: '0', dir: 'ltr' }, d.example) : null),
        h('li', null, t('tools.mcp.step2')),
        h('li', null, t('tools.mcp.step3'))),
      d.guide ? h('a', { href: d.guide, target: '_blank', rel: 'noopener' }, t('tools.mcp.guide')) : null),
  ];
}

export function mount(root, { api, store }) {
  const mcp = h('div'), reg = h('div'), recent = h('div'), files = h('p', { class: 'muted' });
  const render = (d) => { mcp.replaceChildren(...mcpPanel(d, trust).flat().filter(Boolean)); reg.replaceChildren(registry(d.items || [])); };
  const load = async (call) => {
    reload.disabled = true;
    reload.setAttribute('aria-busy', 'true');
    try { await loadInto(reg, call, render, t('tools.loadError')); }
    finally { reload.disabled = false; reload.removeAttribute('aria-busy'); }
  };
  const trust = (digest) => load(() => api.trustTools(digest));
  const reload = button(t('tools.reload'), { onClick: () => load(() => api.reloadTools()) });
  const box = createSandbox({ api, store });
  root.append(viewShell('tools', section(t('tools.mcp.title'), h('div', { class: 'row' }, reload), mcp), section(t('tools.registry'), reg), section(t('files.title'), files), section(t('tools.recent'), recent), section(t('tools.sandboxTitle'), box.el)));
  api.files().then((f) => { files.textContent = f.on ? t('files.on', { allow: f.allow, deny: f.deny, file: f.settings }) : t('files.off'); }).catch(() => {});
  loadInto(reg, () => api.tools(), render, t('tools.loadError'));
  const paint = () => recent.replaceChildren(recentCalls(store.get().session));
  paint();
  const unsub = store.subscribe(paint, ['session']);
  return () => { unsub(); box.dispose(); };
}
