// File access rules (.sensai/settings.json): one rule per line; a confirm card shows before and after, nothing is saved before yes.
import { h } from '../dom.js';
import { button } from '../components/button.js';
import { field, textarea } from '../components/form.js';
import { openModal } from '../components/modal.js';
import { toast } from '../components/toast.js';
import { t } from '../i18n.js';

const lines = (box) => box.value.split('\n').map((l) => l.trim()).filter(Boolean);
const listOf = (rules) => (rules.length ? h('ul', { class: 'mono' }, rules.map((r) => h('li', null, r))) : h('p', { class: 'muted' }, t('rules.none')));

export function createRulesCard({ api }) {
  const status = h('p', { class: 'muted' });
  const allow = textarea({ rows: 4, class: 'textarea mono', spellcheck: 'false' });
  const deny = textarea({ rows: 3, class: 'textarea mono', spellcheck: 'false' });
  const err = h('p', { class: 'field__error', role: 'alert', hidden: true });
  const save = button(t('rules.review'), { variant: 'primary', onClick: review });
  const el = h('div', { class: 'stack' }, h('p', { class: 'muted' }, t('rules.help')), status,
    field(t('rules.allow'), allow, { help: t('rules.allowHelp') }), field(t('rules.deny'), deny, { help: t('rules.denyHelp') }),
    h('div', { class: 'row' }, save), err);

  function render(d) {
    status.textContent = d.on ? t('rules.on', { file: d.file }) : t('rules.off', { file: d.file });
    allow.value = d.allow.join('\n');
    deny.value = d.deny.join('\n');
  }

  async function review() {
    err.hidden = true;
    let p;
    try { p = await api.proposeRules(lines(allow), lines(deny)); } catch (e) { err.textContent = e.message; err.hidden = false; return; }
    const decide = (approved) => async (close) => {
      close();
      try { const d = await api.confirmRules(p.token, approved); render(d); if (approved) toast(t('rules.saved')); }
      catch (e) { err.textContent = e.message; err.hidden = false; }
    };
    const side = (title, r) => h('div', { class: 'stack' }, h('h3', null, title), h('strong', null, t('rules.allow')), listOf(r.allow), h('strong', null, t('rules.deny')), listOf(r.deny));
    openModal({ title: t('rules.confirmTitle'), wide: true, dismissible: false,
      body: h('div', { class: 'stack' }, h('p', null, t('rules.confirmBody')), h('div', { class: 'row' }, side(t('rules.before'), p.before), side(t('rules.after'), p.after))),
      actions: [{ label: t('rules.keep'), onClick: decide(false) }, { label: t('rules.apply'), variant: 'primary', onClick: decide(true) }] });
  }

  api.fileRules().then(render, (e) => { err.textContent = e.message; err.hidden = false; });
  return { el };
}
