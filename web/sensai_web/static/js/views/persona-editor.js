// Persona editor: one dialog to add, edit or remove a persona. The id is fixed once created.
import { h } from '../dom.js';
import { openModal } from '../components/modal.js';
import { field, input, textarea } from '../components/form.js';
import { t } from '../i18n.js';

const slug = (name) => name.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40);

export function openPersonaEditor({ persona, existing, actions, canRemove }) {
  const isNew = !persona;
  const name = input({ value: persona?.name || '', maxlength: 80, autocomplete: 'off' });
  const id = input({ value: persona?.id || '', class: 'input mono', disabled: !isNew, autocomplete: 'off' });
  const tone = input({ value: persona?.tone || '', maxlength: 200, autocomplete: 'off' });
  const role = textarea({ rows: 3, maxlength: 2000 }); role.value = persona?.role || '';
  const scope = textarea({ rows: 3, maxlength: 2000 }); scope.value = persona?.response_scope || '';
  const err = h('p', { class: 'field__error', role: 'alert', hidden: true });
  let touchedId = !isNew;
  id.addEventListener('input', () => { touchedId = true; });
  name.addEventListener('input', () => { if (!touchedId) id.value = slug(name.value); });
  const body = h('form', { class: 'stack', novalidate: true },
    field(t('personas.fieldName'), name), field(t('personas.fieldId'), id, { help: isNew ? t('personas.idHelp') : t('personas.idFixed') }),
    field(t('persona.tone'), tone), field(t('personas.role'), role), field(t('personas.scope'), scope, { help: t('personas.scopeHelp') }), err);
  const fail = (m) => { err.textContent = m; err.hidden = false; };
  const save = async (close) => {
    err.hidden = true;
    const key = id.value.trim();
    if (!key) return fail(t('personas.needId'));
    if (isNew && existing.includes(key)) return fail(t('personas.idTaken'));
    try { await actions.savePersona(key, { name: name.value, tone: tone.value, role: role.value, response_scope: scope.value }); close(); }
    catch (e) { fail(e.message); }
  };
  const remove = async (close) => { try { await actions.deletePersona(persona.id); close(); } catch (e) { fail(e.message); } };
  body.addEventListener('submit', (e) => e.preventDefault());
  const m = openModal({ title: t(isNew ? 'personas.newTitle' : 'personas.editTitle'), body, wide: true, actions: [
    ...(isNew || !canRemove ? [] : [{ label: t('personas.remove'), variant: 'danger', onClick: remove }]),
    { label: t('common.cancel'), onClick: (c) => c() }, { label: t('common.save'), variant: 'primary', onClick: save }] });
  name.focus();
  return m;
}
