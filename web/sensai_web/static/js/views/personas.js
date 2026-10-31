// Personas view (spec 8.1): catalogue cards. Personas are added, edited and removed here and saved to the catalogue file.
import { h } from '../dom.js';
import { chip } from '../components/chip.js';
import { button } from '../components/button.js';
import { openPersonaEditor } from './persona-editor.js';
import { viewShell } from '../components/view.js';
import { emptyState } from '../components/state.js';
import { personaTone } from '../components/topbar.js';
import { t } from '../i18n.js';

const labelled = (label, text) => h('div', null, h('div', { class: 'label-s' }, label), h('p', null, text || t('common.na')));

export function mount(root, { store, actions }) {
  const custom = store.get().personasSource && store.get().personasSource !== 'builtin';
  const grid = h('div', { class: 'persona-grid' });
  root.append(viewShell('personas',
    h('div', { class: 'banner banner--info banner--inline', role: 'note' }, h('span', { class: 'banner__text' }, custom ? t('personas.custom', { file: store.get().personasSource }) : t('personas.builtin'))),
    h('div', { class: 'row' }, h('p', { class: 'muted grow' }, t('personas.editHelp')), button(t('personas.new'), { variant: 'primary', icon: 'plus', onClick: () => openPersonaEditor({ existing: store.get().personas.map((p) => p.id), actions }) })), grid));

  function paint() {
    const { personas, activePersona, status } = store.get();
    if (!personas.length) return grid.replaceChildren(emptyState({ icon: 'persona', title: t('personas.none') }));
    grid.replaceChildren(...personas.map((p, i) => {
      const active = p.id === activePersona;
      return h('article', { class: `card stack persona-card ${active ? 'is-active' : ''}`, 'aria-labelledby': `pc-${p.id}` },
        h('div', { class: 'row' }, h('span', { class: 'avatar avatar--lg', dataset: { tone: personaTone(i) }, 'aria-hidden': 'true' }, (p.name || '?')[0].toUpperCase()),
          h('div', { class: 'grow' }, h('h2', { id: `pc-${p.id}`, class: 'persona-card__name' }, p.name), chip(p.id, { mono: true, outline: true })),
          active ? chip(t('personas.active'), { tone: 'sage', icon: 'check' }) : null),
        labelled(t('persona.tone'), p.tone), labelled(t('personas.role'), p.role), labelled(t('personas.scope'), p.response_scope),
        h('p', { class: 'muted persona-card__guard' }, t('personas.guard')),
        h('div', { class: 'row' }, button(active ? t('personas.inUse') : t('personas.use'), { variant: active ? 'secondary' : 'primary', disabled: active || status.streaming, onClick: () => actions.setPersona(p.id), 'data-tip': status.streaming ? t('persona.waitTip') : null }),
          button(t('personas.edit'), { variant: 'ghost', icon: 'edit', disabled: status.streaming, onClick: () => openPersonaEditor({ persona: p, existing: [], actions, canRemove: personas.length > 1 }) })));
    }));
  }
  paint();
  return store.subscribe(paint, ['personas', 'activePersona', 'status']);
}
