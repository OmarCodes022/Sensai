// Command box with before/after approval card (preview only) and the weekly-run summary.
import { h } from '../../dom.js';
import { chip } from '../../components/chip.js';
import { button } from '../../components/button.js';
import { EDIT, RUN, WEEK } from '../../mock/planned-campaign.js';
import { t } from '../../i18n.js';

export function commandBox(isApproved) {
  const out = h('div', { 'aria-live': 'polite' });
  const input = h('input', { class: 'input mono', value: EDIT.cmd, 'aria-label': t('campaign.cmd'), 'aria-describedby': 'cmd-help' });
  const result = (text) => out.replaceChildren(h('p', { class: 'muted', role: 'status' }, text));
  const card = () => {
    const approved = isApproved();
    const decide = (ok) => result(ok ? t('campaign.previewApplied') : t('campaign.noChange'));
    out.replaceChildren(h('div', { class: 'card approval-mini stack', role: 'group', 'aria-label': t('campaign.applyQ') },
      h('div', { class: 'row' }, h('b', null, t('campaign.applyQ')), approved ? chip(t('campaign.postsApproved'), { tone: 'sage', icon: 'lock' }) : chip(t('campaign.autoDraft'), { tone: 'amber' })),
      h('p', null, t('campaign.action'), ': ', t('campaign.replacePost', { id: EDIT.target }), h('br'), t('campaign.where'), ': ', h('code', null, WEEK.file)),
      h('div', { class: 'muted' }, t('campaign.before')), h('div', { class: 'diff diff--del', dir: 'auto' }, EDIT.before),
      h('div', { class: 'muted' }, t('campaign.after')), h('div', { class: 'diff diff--add', dir: 'auto' }, EDIT.after),
      h('div', { class: 'row' }, button(`${t('common.refuse')} (n)`, { onClick: () => decide(false) }), button(`${t('campaign.apply')} (y)`, { variant: 'primary', onClick: () => decide(true) }))));
  };
  const bad = () => result(t('campaign.invalidEdit'));
  return h('div', { class: 'stack' }, h('label', { class: 'field__label', for: 'cmd' }, t('campaign.cmd')),
    h('div', { class: 'row' }, Object.assign(input, { id: 'cmd' }), button(t('campaign.showEdit'), { onClick: () => (input.value.trim() === EDIT.cmd ? card() : bad()) })),
    h('p', { class: 'muted', id: 'cmd-help' }, t('campaign.cmdHelp')), out);
}

export function weeklyRun() {
  return h('div', { class: 'card ribbon stack' }, h('h3', null, t('campaign.weeklyRun')),
    h('ul', { class: 'stack' }, RUN.map(([name, st, text]) => h('li', { class: 'row' }, h('b', null, name), chip(st, { tone: 'sage', icon: 'check' }), h('span', null, text)))),
    h('p', { class: 'muted' }, t('campaign.saved', { file: WEEK.file })));
}
