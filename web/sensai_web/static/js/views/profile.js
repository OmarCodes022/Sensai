// Profile view (spec 8.2): stored preferences, JSON editor with live validation, explicit replace. Never auto-saves.
import { h } from '../dom.js';
import { chip } from '../components/chip.js';
import { button } from '../components/button.js';
import { textarea } from '../components/form.js';
import { confirmDialog } from '../components/modal.js';
import { toast } from '../components/toast.js';
import { emptyState } from '../components/state.js';
import { viewShell, loadInto } from '../components/view.js';
import { validateProfile } from '../profile/validate.js';
import { announce } from '../a11y.js';
import { t } from '../i18n.js';

const EXAMPLE = '{"ton": "direct", "public": "créatrices beauté"}';
const pretty = (o) => JSON.stringify(o, null, 2);

export function mount(root, { api }) {
  const box = h('div', { class: 'stack' });
  root.append(viewShell('profile', box));
  let profile = null, editing = false;

  function show() {
    const keys = Object.entries(profile.preferences || {});
    const empty = !keys.length;
    box.replaceChildren(
      h('div', { class: 'row' }, chip(t('profile.plaintext'), { tone: 'amber', icon: 'alert-triangle' }), chip(t('profile.creatorKey', { key: profile.id }), { mono: true, outline: true })),
      h('p', { class: 'muted' }, t('profile.injected')),
      editing ? editor() : h('div', { class: 'card stack' },
        empty ? emptyState({ icon: 'user', title: t('profile.empty'), body: t('profile.emptyBody', { example: EXAMPLE }), h: 'h2' }) : h('dl', { class: 'kv' }, keys.flatMap(([k, v]) => [h('dt', { class: 'mono' }, k), h('dd', { dir: 'auto' }, String(v))])),
        h('div', null, button(empty ? t('profile.create') : t('profile.edit'), { variant: 'primary', icon: 'edit', onClick: () => { editing = true; show(); box.querySelector('textarea')?.focus(); } }))));
  }

  function editor() {
    const ta = textarea({ rows: 10, class: 'textarea textarea--code', spellcheck: 'false', id: 'profile-ta', 'aria-describedby': 'profile-status' });
    ta.value = Object.keys(profile.preferences || {}).length ? pretty(profile.preferences) : EXAMPLE;
    const status = h('div', { id: 'profile-status', role: 'status', class: 'stack' });
    const save = button(t('profile.replace'), { variant: 'primary', disabled: true });
    const err = h('p', { class: 'field__error', role: 'alert', hidden: true });
    let current = null;
    const check = () => {
      const r = validateProfile(ta.value);
      current = r.value || null;
      ta.setAttribute('aria-invalid', String(!!r.errors));
      save.disabled = !current;
      status.replaceChildren(r.errors ? h('ul', { class: 'bullets' }, r.errors.map((e) => h('li', { class: 'field__error' }, t('profile.line', { n: e.line }), ': ', t(`profile.err.${e.key}`, e.args)))) : h('p', { class: 'muted' }, t('profile.valid', { n: Object.keys(current).length })));
    };
    ta.addEventListener('input', check);
    save.addEventListener('click', async () => {
      if (!current) return;
      const ok = await confirmDialog({ title: t('profile.confirmTitle'), message: t('profile.confirmBody'), confirmLabel: t('profile.replace'), danger: true });
      if (!ok) return;
      save.setAttribute('aria-busy', 'true'); err.hidden = true;
      try {
        const res = await api.putProfile(current);
        profile = res; editing = false; show();
        toast(t('profile.saved')); announce(t('profile.saved'));
      } catch (e) { save.removeAttribute('aria-busy'); err.hidden = false; err.textContent = `${t('err.profile_invalid')} ${e.message}`; }
    });
    check();
    return h('div', { class: 'card stack' }, h('label', { class: 'field__label', for: 'profile-ta' }, t('profile.editor')), ta, status, err,
      h('div', { class: 'row' }, save, button(t('common.cancel'), { onClick: () => { editing = false; show(); } })), h('p', { class: 'muted' }, t('profile.noAuto')));
  }
  loadInto(box, () => api.profile(), (p) => { profile = p; show(); });
}
