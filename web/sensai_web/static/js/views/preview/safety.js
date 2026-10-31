// Safety preview (spec 9.3): rules, adversarial suite with an honest "defined is not executed" banner, evaluation scores.
import { h } from '../../dom.js';
import { chip } from '../../components/chip.js';
import { icon } from '../../icons.js';
import { CLAIMS, RULES, SUITE, EVAL } from '../../mock/planned-misc.js';
import { note, table, mockCard } from './parts.js';
import { t } from '../../i18n.js';

export function mountPreview(root) {
  const approved = CLAIMS.filter((c) => c.approved).length;
  const total = SUITE.reduce((n, r) => n + r[1], 0);
  const sum = (i) => SUITE.reduce((n, r) => n + r[i], 0);
  const score = (name, [a, b]) => h('tr', null, h('th', { scope: 'row' }, t(`safety.${name}`)), h('td', { class: 'num' }, `${a} / 5`), h('td', { class: 'num' }, `${b} / 5`));
  root.replaceChildren(h('div', { class: 'stack' }, note(),
    mockCard(h('h3', null, t('safety.rules')), table([t('safety.direction'), t('safety.action'), t('safety.reason')], RULES.map(([d, a, r]) => [d, chip(a, { outline: true }), chip(r, { mono: true })])),
      h('p', { class: 'muted' }, t('safety.claimsCount', { n: approved }))),
    mockCard(h('h3', null, t('safety.suite')), h('div', { class: 'banner banner--warning banner--inline', role: 'note' }, icon('alert-triangle', { size: 18 }), h('span', { class: 'banner__text' }, t('safety.defined'))),
      table([t('safety.category'), t('safety.cases'), t('safety.hold'), t('safety.fail'), t('safety.notRun')], SUITE.map((r) => [r[0], r[1], chip(String(r[2]), { tone: 'sage' }), chip(String(r[3]), { tone: r[3] ? 'rose' : undefined }), chip(String(r[4]), { outline: true })])),
      h('p', { class: 'muted' }, t('safety.suiteTotal', { total, hold: sum(2), fail: sum(3), none: sum(4) }))),
    mockCard(h('h3', null, t('safety.eval')), h('div', { class: 'table-wrap' }, h('table', { class: 'table' }, h('thead', null, h('tr', null, h('th', null, t('safety.metric')), EVAL.versions.map((v) => h('th', { scope: 'col' }, v)))),
      h('tbody', null, ['relevance', 'coherence', 'faithfulness'].map((k) => score(k, EVAL[k]))))),
      h('h4', null, t('safety.flagged')), h('ul', { class: 'bullets' }, EVAL.flagged.map(([s, k]) => h('li', null, s, ' ', chip(k, { tone: 'rose' })))),
      h('p', { class: 'muted' }, t('safety.planted', { m: EVAL.misses, f: EVAL.falseAlarms })))));
}
