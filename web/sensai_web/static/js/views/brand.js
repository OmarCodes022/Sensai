// Brand facts (M3): the fact sheet the model keeps up to date, editable here, and the approved-claims register.
import { h } from '../dom.js';
import { chip } from '../components/chip.js';
import { button, iconButton } from '../components/button.js';
import { field, input } from '../components/form.js';
import { confirmDialog } from '../components/modal.js';
import { emptyState } from '../components/state.js';
import { tabs } from '../components/tabs.js';
import { toast } from '../components/toast.js';
import { viewShell } from '../components/view.js';
import { table } from './preview/parts.js';
import { claimStatus } from './preview/brand.js';
import { announce } from '../a11y.js';
import { t } from '../i18n.js';

export function mount(root, { api }) {
  let items = [];
  const list = h('div', { class: 'stack' });
  const id = input({ class: 'input mono', placeholder: 'hydra-glow-serum.price', autocomplete: 'off', maxlength: 160 });
  const text = input({ placeholder: t('brand.textPlaceholder'), autocomplete: 'off', maxlength: 300 });
  const err = h('p', { class: 'field__error', role: 'alert', hidden: true });
  const save = button(t('brand.saveFact'), { variant: 'primary', icon: 'plus', type: 'submit' });
  const form = h('form', { class: 'card stack', novalidate: true },
    h('h2', null, t('brand.addTitle')), h('div', { class: 'row' }, field(t('brand.id'), id), field(t('brand.text'), text)),
    h('p', { class: 'muted' }, t('brand.idHelp')), err, h('div', null, save));
  const fail = (m) => { err.textContent = m; err.hidden = false; };

  function paint() {
    if (!items.length) return list.replaceChildren(emptyState({ icon: 'database', title: t('brand.noFacts'), body: t('brand.factsNote') }));
    list.replaceChildren(table([t('brand.id'), t('brand.text'), t('brand.source'), ''], items.map((f) => [
      h('code', null, f.id), h('span', { dir: 'auto' }, f.text), h('span', { class: 'muted' }, f.source),
      h('span', { class: 'row' },
        iconButton('edit', t('brand.edit', { id: f.id }), { variant: 'ghost', size: 'sm', onClick: () => { id.value = f.id; text.value = f.text; text.focus(); } }),
        iconButton('trash', t('brand.delete', { id: f.id }), { variant: 'ghost', size: 'sm', onClick: () => remove(f.id) }))])));
  }

  async function remove(factId) {
    if (!(await confirmDialog({ title: t('brand.deleteTitle'), message: t('brand.deleteBody', { id: factId }), confirmLabel: t('brand.deleteConfirm'), danger: true }))) return;
    try { items = (await api.deleteFact(factId)).items; paint(); toast(t('brand.deleted', { id: factId })); announce(t('brand.deleted', { id: factId })); }
    catch (e) { toast(e.message, { tone: 'rose' }); }
  }

  form.addEventListener('submit', async (e) => {
    e.preventDefault(); err.hidden = true;
    try {
      items = (await api.putFact(id.value.trim(), text.value)).items; paint();
      toast(t('brand.saved', { id: id.value.trim() })); announce(t('brand.saved', { id: id.value.trim() }));
      id.value = ''; text.value = '';
    } catch (ex) { fail(ex.message); }
  });

  const facts = () => h('div', { class: 'stack' }, h('p', { class: 'muted' }, t('brand.factsNote'), ' ', t('brand.perCreator')), list, form);
  const claims = () => {
    const box = h('div', { class: 'stack' }, h('p', { class: 'muted' }, t('brand.readOnly')));
    api.brandClaims().then(({ file, items: rows }) => {
      if (!file) return box.append(emptyState({ icon: 'star', title: t('brand.noClaims'), body: t('brand.noClaimsBody') }));
      const today = new Date().toISOString().slice(0, 10);
      box.append(table([t('brand.id'), t('brand.product'), t('brand.text'), t('brand.source'), t('brand.from'), t('brand.until'), t('brand.status')],
        rows.map((c) => { const [tone, key] = claimStatus(c, today); return [h('code', null, c.id), c.product, c.text, c.source || t('common.na'), c.from || t('common.na'), c.until || t('common.na'), chip(t(`brand.st.${key}`), { tone })]; })));
    }).catch((e) => box.append(h('p', { class: 'field__error' }, e.message)));
    return box;
  };

  root.append(viewShell('brand', tabs({ label: t('nav.brand'), selected: 'facts', items: [{ id: 'facts', label: t('brand.facts'), render: facts }, { id: 'claims', label: t('brand.claims'), render: claims }] })));
  api.facts().then((d) => { items = d.items; paint(); }).catch((e) => list.replaceChildren(h('p', { class: 'field__error' }, e.message)));
}
