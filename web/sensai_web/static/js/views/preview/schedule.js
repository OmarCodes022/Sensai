// Schedule preview (spec 9.5 / T51): tasks, drafts folder, failure rows. Runs only prepare drafts.
import { h } from '../../dom.js';
import { chip } from '../../components/chip.js';
import { icon } from '../../icons.js';
import { TASKS, DRAFTS } from '../../mock/planned-misc.js';
import { note, table, mockCard } from './parts.js';
import { t } from '../../i18n.js';

export function mountPreview(root) {
  root.replaceChildren(h('div', { class: 'stack' }, note(),
    h('div', { class: 'banner banner--info banner--inline', role: 'note' }, icon('info', { size: 18 }), h('span', { class: 'banner__text' }, t('schedule.banner'))),
    mockCard(table([t('schedule.name'), t('schedule.prompt'), t('nav.personas'), t('schedule.every'), t('schedule.last'), t('schedule.next'), t('tools.col.status')],
      TASKS.map((x) => [x.name, x.prompt, x.persona, t('schedule.minutes', { n: x.every }), x.last, x.next, chip(t(`schedule.st.${x.status}`), { tone: x.status === 'ok' ? 'sage' : 'rose' })])),
      ...TASKS.filter((x) => x.status === 'failed').map((x) => h('p', { class: 'field__error', role: 'status' }, icon('alert-triangle', { size: 14 }), ' ', t('schedule.retry', { name: x.name })))),
    mockCard(h('h3', null, t('schedule.drafts')), h('ul', { class: 'stack' }, DRAFTS.map(([f, p]) => h('li', { class: 'stack' }, h('code', null, f), h('p', { class: 'muted', dir: 'auto' }, p)))))));
}
