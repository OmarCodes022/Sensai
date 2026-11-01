// Safety (EV1): check an answer against the brand documents, and the saved evaluation runs with what they flagged.
import { h } from '../dom.js';
import { chip } from '../components/chip.js';
import { button } from '../components/button.js';
import { field, input, textarea } from '../components/form.js';
import { emptyState } from '../components/state.js';
import { viewShell } from '../components/view.js';
import { table } from './preview/parts.js';
import { announce } from '../a11y.js';
import { t } from '../i18n.js';

const TONE = { supported: 'sage', unsupported: 'amber', contradicted: 'rose' };
const section = (title, ...kids) => h('section', { class: 'stack' }, h('h2', null, title), ...kids);
const scores = (r) => h('div', { class: 'row' }, ['relevance', 'coherence', 'faithfulness'].map((k) =>
  chip(`${t(`safety.${k}`)} ${r[k] ?? t('common.na')}${typeof r[k] === 'number' && Number.isInteger(r[k]) ? '/5' : ''}`, { outline: true })));
const statement = (s) => h('li', { class: 'row' }, chip(t(`safety.label.${s.label}`), { tone: TONE[s.label] }),
  h('span', { dir: 'auto' }, s.text), s.source ? h('code', { class: 'muted' }, s.source) : null);

export function mount(root, { api, router }) {
  const question = input({ placeholder: t('safety.questionPlaceholder'), autocomplete: 'off' });
  const answer = textarea({ placeholder: t('safety.answerPlaceholder'), rows: 4 });
  const out = h('div', { class: 'stack', 'aria-live': 'polite' });
  const runs = h('div', { class: 'stack' });
  const go = button(t('safety.check'), { variant: 'primary', icon: 'shield', type: 'submit' });
  const form = h('form', { class: 'card stack', novalidate: true }, h('p', { class: 'muted' }, t('safety.checkHelp')),
    field(t('safety.question'), question), field(t('safety.answer'), answer), h('div', null, go), out);

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    go.disabled = true; out.replaceChildren(h('p', { class: 'muted', role: 'status' }, t('safety.checking')));
    try {
      const r = await api.evaluationCheck(question.value, answer.value);
      const summary = r.flagged ? t('safety.flaggedCount', { n: r.flagged }) : t('safety.allSupported');
      out.replaceChildren(scores(r), h('p', null, h('strong', null, summary)), h('ul', { class: 'stack' }, r.statements.map(statement)),
        h('details', null, h('summary', null, t('safety.sources')), h('pre', { class: 'mono' }, r.sources || t('safety.noSources'))));
      announce(summary);
    } catch (err) { out.replaceChildren(h('p', { class: 'field__error', role: 'alert' }, err.message)); }
    finally { go.disabled = false; }
  });

  root.append(viewShell('safety', section(t('safety.checkTitle'), form),
    section(t('safety.runsTitle'), h('p', { class: 'muted' }, t('safety.runsHelp'), ' ', h('code', null, 'evals/faithfulness/run.py')), runs),
    section(t('safety.claimsTitle'), h('p', { class: 'muted' }, t('safety.claimsHelp')),
      h('div', null, button(t('safety.openClaims'), { icon: 'star', onClick: () => router.go('#/brand') })))));

  api.evaluation().then(({ runs: items }) => {
    if (!items.length) return runs.replaceChildren(emptyState({ icon: 'chart', title: t('safety.noRuns'), h: 'h3' }));
    runs.replaceChildren(table([t('safety.version'), t('safety.model'), t('safety.search'), t('safety.relevance'), t('safety.coherence'), t('safety.faithfulness'), t('safety.flaggedCol')],
      items.map((r) => [h('b', null, r.label), `${r.model} / ${r.judge}`, r.search, r.relevance ?? t('common.na'), r.coherence ?? t('common.na'), r.faithfulness ?? t('common.na'), String(r.flagged.length)])),
    ...items.filter((r) => r.flagged.length).map((r) => h('details', { class: 'card stack' }, h('summary', null, t('safety.flaggedIn', { label: r.label, n: r.flagged.length })),
      h('ul', { class: 'stack' }, r.flagged.map((s) => h('li', { class: 'stack' }, h('span', { class: 'muted' }, `Q${s.n} ${s.question}`), statement(s)))))));
  }).catch((err) => runs.replaceChildren(h('p', { class: 'field__error' }, err.message)));
}
