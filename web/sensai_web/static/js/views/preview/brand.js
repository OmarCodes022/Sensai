// Brand facts preview (spec 9.2): claims register (read-only) and facts memory.
import { h } from '../../dom.js';
import { chip } from '../../components/chip.js';
import { tabs } from '../../components/tabs.js';
import { CLAIMS, FACTS, TODAY } from '../../mock/planned-misc.js';
import { note, table, mockCard } from './parts.js';
import { t } from '../../i18n.js';

const DAY = 86400000;
/** Returns [tone, key] for a claim relative to TODAY. */
export function claimStatus(c, today = TODAY) {
  if (!c.approved) return ['rose', 'notApproved'];
  const left = (Date.parse(c.until) - Date.parse(today)) / DAY;
  if (left < 0) return ['rose', 'expired'];
  return left <= 90 ? ['amber', 'expiring'] : ['sage', 'valid'];
}

export function mountPreview(root) {
  const claims = () => mockCard(h('p', { class: 'muted' }, t('brand.readOnly')),
    table([t('brand.id'), t('brand.product'), t('brand.text'), t('brand.source'), t('brand.from'), t('brand.until'), t('brand.status')],
      CLAIMS.map((c) => { const [tone, key] = claimStatus(c); return [h('code', null, c.id), c.product, c.text, c.source || t('common.na'), c.from || t('common.na'), c.until || t('common.na'), chip(t(`brand.st.${key}`), { tone })]; })));
  const facts = () => mockCard(h('p', { class: 'muted' }, t('brand.factsNote')),
    table([t('brand.id'), t('brand.text'), t('brand.source'), t('brand.updated')], FACTS.map((f) => [h('code', null, f.id), f.text, f.source, f.updated])),
    h('div', { class: 'row' }, chip(t('brand.memUpdated', { id: FACTS[0].id }), { tone: 'plum', icon: 'database' }), chip(t('brand.memWill', { id: FACTS[2].id }), { tone: 'plum', outline: true })),
    h('p', { class: 'muted' }, t('brand.perCreator')));
  root.replaceChildren(h('div', { class: 'stack' }, note(), tabs({ label: t('nav.brand'), items: [{ id: 'claims', label: t('brand.claims'), render: claims }, { id: 'facts', label: t('brand.facts'), render: facts }] })));
}
