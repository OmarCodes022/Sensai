// Posts and DM replies panels. DMs never show names, handles or contact details; left-out DMs show no content.
import { h } from '../../dom.js';
import { icon } from '../../icons.js';
import { chip } from '../../components/chip.js';
import { POSTS, DMS, LEFT_OUT } from '../../mock/planned-campaign.js';
import { t } from '../../i18n.js';

export function postsPanel() {
  const blocked = POSTS.find((p) => !p.claim.ok);
  return h('div', { class: 'stack' },
    blocked ? h('div', { class: 'banner banner--error banner--inline', role: 'alert' }, icon('x-circle', { size: 18 }), h('span', { class: 'banner__text' }, t('campaign.exportBlocked', { id: blocked.id }))) : null,
    h('div', { class: 'cards-3' }, POSTS.map((p) => h('article', { class: 'card ribbon stack', 'aria-label': p.id },
      h('div', { class: 'row' }, h('b', { class: 'mono' }, p.id), h('span', { class: 'grow' }), h('span', { class: 'muted' }, 'Instagram')),
      h('p', { class: 'post__text', dir: 'auto' }, p.text),
      h('div', { class: 'row' }, chip(`${p.claim.id} ${p.claim.note}`, { tone: p.claim.ok ? 'sage' : 'rose', icon: p.claim.ok ? 'check' : 'alert-triangle' }), chip(t(p.claim.ok ? 'campaign.valid' : 'campaign.invalid'), { outline: true })),
      h('p', { class: p.claim.ok ? 'muted' : 'field__error' }, p.claim.ok ? t('campaign.neverPublished') : t('campaign.exportBlocked', { id: p.id }))))));
}

export function dmPanel() {
  return h('div', { class: 'stack' },
    h('p', { class: 'chip chip--outline' }, t('campaign.dmCounters', { s: DMS.length, o: LEFT_OUT.length })),
    h('div', { class: 'cards-3' }, DMS.map((d) => h('article', { class: 'card ribbon stack', 'aria-label': d.id },
      h('div', { class: 'row' }, h('b', { class: 'mono' }, d.id), h('span', { class: 'grow' }), chip(t('campaign.unsent'), { tone: 'amber' })),
      h('p', { class: 'muted' }, t('campaign.question')), h('p', { dir: 'auto' }, d.q), h('p', { class: 'muted' }, t('campaign.suggestion')), h('p', { dir: 'auto' }, d.reply)))),
    h('ul', { class: 'stack' }, LEFT_OUT.map((r) => h('li', { class: 'row left-out' }, icon('eye-off', { size: 16 }), t('campaign.leftOut', { reason: r })))));
}
