// Personas view (spec 8.1): catalogue cards, read-only. Editing is by file, and the page says so.
import { h } from '../dom.js';
import { chip } from '../components/chip.js';
import { button } from '../components/button.js';
import { copyButton } from '../components/copy-button.js';
import { viewShell } from '../components/view.js';
import { emptyState } from '../components/state.js';
import { personaTone } from '../components/topbar.js';
import { t } from '../i18n.js';

const SHAPE = `[
  {
    "id": "redaction",
    "name": "Rédaction",
    "tone": "warm",
    "role": "Drafts posts and captions for validation.",
    "response_scope": "Drafts only. Nothing is published."
  }
]`;
const ERRORS = ['missing', 'extra', 'blank', 'duplicate', 'unknown'];

const labelled = (label, text) => h('div', null, h('div', { class: 'label-s' }, label), h('p', null, text || t('common.na')));

export function mount(root, { store, actions }) {
  const custom = store.get().personasSource && store.get().personasSource !== 'builtin';
  const help = h('details', { class: 'card' }, h('summary', null, t('personas.howTitle')),
    h('div', { class: 'stack' }, h('p', null, t('personas.howIntro')),
      h('div', { class: 'row' }, h('strong', null, t('personas.shape')), copyButton(() => SHAPE, { label: t('common.copy') })),
      h('pre', { class: 'code', tabindex: '0' }, SHAPE),
      h('p', null, t('personas.required')),
      h('h3', null, t('personas.errorsTitle')), h('ul', { class: 'bullets' }, ERRORS.map((k) => h('li', null, t(`personas.err.${k}`))))));
  const grid = h('div', { class: 'persona-grid' });
  root.append(viewShell('personas',
    h('div', { class: 'banner banner--info banner--inline', role: 'note' }, h('span', { class: 'banner__text' }, custom ? t('personas.custom', { file: store.get().personasSource }) : t('personas.builtin'))),
    h('p', { class: 'muted' }, t('personas.readOnly')), help, grid));

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
        button(active ? t('personas.inUse') : t('personas.use'), { variant: active ? 'secondary' : 'primary', disabled: active || status.streaming, onClick: () => actions.setPersona(p.id), 'data-tip': status.streaming ? t('persona.waitTip') : null }));
    }));
  }
  paint();
  return store.subscribe(paint, ['personas', 'activePersona', 'status']);
}
