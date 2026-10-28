import { h } from '../dom.js';
import { emptyState } from '../components/state.js';
import { hrefFor, ROUTES } from '../router.js';
import { t } from '../i18n.js';

export function mount(root, { router }) {
  document.title = `${t('notfound.title')} - Sensai`;
  const links = ROUTES.filter((r) => r.live).map((r) => h('a', { class: 'btn', href: hrefFor(r.name) }, t(`nav.${r.name}`)));
  root.append(h('div', { class: 'view' }, h('h1', { class: 'sr-only' }, t('notfound.title')),
    emptyState({ icon: 'map', title: t('notfound.title'), body: t('notfound.body', { path: router.current?.raw || '' }) }),
    h('div', { class: 'row' }, links)));
}
