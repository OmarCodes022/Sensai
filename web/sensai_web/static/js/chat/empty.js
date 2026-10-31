// Empty state for a new conversation: greeting, persona-aware starter prompts, privacy line (spec 6.2).
import { h } from '../dom.js';
import { seal } from '../icons.js';
import { chip } from '../components/chip.js';
import { t } from '../i18n.js';

const fallback = (id) => [1, 2, 3].map((n) => t(`starter.${id}.${n}`)).filter((s) => !s.startsWith('starter.'));

/** deps: { store, getName(), onStarter(text) }. update() repaints for the active persona. */
export function createEmpty({ store, getName, onStarter }) {
  const el = h('div', { class: 'chat-empty' });
  function update() {
    const s = store.get();
    const p = s.personas.find((x) => x.id === s.activePersona);
    const starters = p?.starters?.length ? p.starters : p ? fallback(p.id) : [];
    const name = getName();
    el.replaceChildren(
      h('span', { class: 'chat-empty__seal' }, seal()),
      h('h2', null, name ? t('chat.greetingName', { name }) : t('chat.greeting')),
      h('div', { class: 'chat-empty__starters', role: 'group', 'aria-label': t('chat.starters') }, starters.map((text) => h('button', { type: 'button', class: 'btn btn--pill', onclick: () => onStarter(text) }, text))),
      h('p', { class: 'muted' }, t('everything.local')),
      h('div', { class: 'row' }, p ? chip(p.name, { tone: 'accent' }) : null, chip(s.status.health?.model?.name || s.config?.model || t('common.na'), { mono: true, outline: true })));
  }
  update();
  return { el, update };
}
