// Keynote launcher (spec 8.9). The presenter bar and body class live in keynote/bar.js.
import { h } from '../dom.js';
import { button } from '../components/button.js';
import { check, field } from '../components/form.js';
import { select } from '../components/form.js';
import { chip } from '../components/chip.js';
import { viewShell } from '../components/view.js';
import { startKeynote, stopKeynote, keynoteActive } from '../keynote/bar.js';
import { playable } from '../keynote/beats.js';
import { t } from '../i18n.js';

export function mount(root, { store, router, api }) {
  const mock = api.mode === 'mock';
  const hasMonday = playable().some((s) => s.id === 'monday');
  if (!mock) {
    root.append(viewShell('keynote', h('div', { class: 'card stack' }, h('p', null, t('keynote.needsMock')),
      h('a', { class: 'btn btn--primary', href: `${location.pathname}?mock=1#/keynote` }, t('keynote.openMock')))));
    return;
  }
  const sel = select(playable().map((s) => [s.id, `${s.n}. ${s.title}`]));
  if (hasMonday) sel.value = 'monday';
  const rec = check(t('keynote.record'));
  const go = button(t('keynote.start'), { variant: 'primary', size: 'lg', icon: 'play', onClick: () => startKeynote({ scenarioId: sel.value, router, store, record: rec.querySelector('input').checked }) });
  root.append(viewShell('keynote', h('p', { class: 'muted' }, t('keynote.intro')),
    h('div', { class: 'card stack' }, chip(t('common.mockData'), { tone: 'amber' }), field(t('keynote.scenario'), sel), rec, h('p', { class: 'muted' }, t('keynote.recordHelp')), h('div', { class: 'row' }, go,
      keynoteActive() ? button(t('keynote.exit'), { onClick: stopKeynote }) : null)),
    h('p', { class: 'muted' }, t('keynote.keys'))));
}
