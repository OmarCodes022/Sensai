// ask_user form (X4): the model's questions as choices or text boxes; Send answers them, Skip skips them.
import { h, nextId } from '../dom.js';
import { icon } from '../icons.js';
import { button } from '../components/button.js';
import { t } from '../i18n.js';

/** ev: {id, questions:[{type, text, options}]}. send(answers) and skip() talk to the backend. */
export function createQuestionCard(ev, { send, skip }) {
  let open = true;
  const err = h('p', { class: 'field__error', role: 'alert', hidden: true });
  const fields = ev.questions.map((q) => {
    const name = nextId('q');
    if (q.type === 'text') {
      const input = h('input', { class: 'input', 'aria-label': q.text, autocomplete: 'off' });
      return { el: h('label', { class: 'stack' }, h('span', null, q.text), input), value: () => input.value.trim(), first: input };
    }
    const other = h('input', { class: 'input', placeholder: t('question.otherPlaceholder'), 'aria-label': t('question.other'), hidden: true });
    const radios = [...q.options, null].map((o) => h('input', { type: 'radio', name, value: o ?? '' }));
    radios.forEach((r) => r.addEventListener('change', () => { other.hidden = r.value !== '' || !r.checked; if (!other.hidden) other.focus(); }));
    const el = h('fieldset', { class: 'stack' }, h('legend', null, q.text),
      ...radios.map((r, i) => h('label', { class: 'check' }, r, h('span', null, i < q.options.length ? q.options[i] : t('question.other')))), other);
    return { el, value: () => { const r = radios.find((x) => x.checked); return !r ? '' : r.value || other.value.trim(); }, first: radios[0] };
  });
  const sendBtn = button(t('question.send'), { variant: 'primary', icon: 'send' });
  const skipBtn = button(t('question.skip'));
  const status = h('p', { class: 'muted', role: 'status' });
  const el = h('section', { class: 'card approval-mini stack question-card', 'aria-label': t('question.title') },
    h('div', { class: 'row' }, icon('info', { size: 18 }), h('b', null, t('question.title'))),
    ...fields.map((f) => f.el), err, h('div', { class: 'row' }, skipBtn, sendBtn), status);
  const lock = () => { open = false; el.querySelectorAll('input, button').forEach((x) => { x.disabled = true; }); };
  sendBtn.addEventListener('click', async () => {
    const answers = fields.map((f) => f.value());
    if (answers.some((a) => !a)) { err.textContent = t('question.answerAll'); err.hidden = false; return; }
    err.hidden = true; lock();
    try { await send(answers); } catch (e) { open = true; el.querySelectorAll('input, button').forEach((x) => { x.disabled = false; }); err.textContent = e.message; err.hidden = false; }
  });
  skipBtn.addEventListener('click', async () => { lock(); try { await skip(); } catch { /* the turn ends anyway */ } });
  return {
    el,
    callId: ev.call_id,
    finished() {},  // Approvals use this when their tool ends; a form is settled by question_result.
    isOpen: () => open,
    focus: () => fields[0]?.first?.focus(),
    finish(skipped) { lock(); status.textContent = t(skipped ? 'question.skipped' : 'question.answered'); el.classList.add('approval--done'); },
    dispose() { lock(); },
  };
}
