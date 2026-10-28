// Floating mock controls: scenario, stream speed, error injection, reset, JSON export. Ctrl/Cmd+Shift+D.
import { h } from '../dom.js';
import { hasMod } from '../platform.js';
import { exportScript, ERRORS } from './scenarios.js';
import { SPEED } from './player.js';
import { t } from '../i18n.js';

const download = (name, text) => {
  const a = h('a', { href: URL.createObjectURL(new Blob([text], { type: 'application/json' })), download: name });
  document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
};
const sel = (label, options, value, onChange) => {
  const s = h('select', { class: 'select', 'aria-label': label }, options.map(([v, l]) => h('option', { value: v }, l)));
  s.value = value; s.addEventListener('change', () => onChange(s.value));
  return h('label', { class: 'field' }, h('span', { class: 'field__label' }, label), s);
};

export function installDevPanel(ctl) {
  if (document.querySelector('.devpanel')) return;
  const keynote = () => document.body.classList.contains('keynote') || location.hash === '#/keynote';
  const info = h('p', { class: 'muted', role: 'status' });
  const hint = h('p', { class: 'devpanel__prompt mono' });
  const paintInfo = () => {
    const sc = ctl.scenarios.find((x) => x.id === ctl.state.scenario);
    info.textContent = t('dev.turn', { i: Math.min(ctl.state.turnIdx, sc.turns.length), n: sc.turns.length });
    hint.textContent = sc.prompt || '';
    scenario.querySelector('select').value = sc.id;
  };
  const apply = (id) => {
    ctl.select(id);
    if (location.hash !== '#/chat') location.hash = '#/chat'; else dispatchEvent(new HashChangeEvent('hashchange'));
  };
  const scenario = sel(t('dev.scenario'), ctl.scenarios.map((s) => [s.id, `${s.n}. ${s.title}${s.planned ? ` (${t('common.planned')})` : ''}`]), ctl.state.scenario, apply);
  const inject = sel(t('dev.inject'), [['', t('dev.none')], ...Object.keys(ERRORS).map((k) => [k, k])], '', (v) => ctl.set({ inject: v || null }));
  const speed = sel(t('dev.speed'), Object.keys(SPEED).map((k) => [k, k]), ctl.state.speed, (v) => ctl.set({ speed: v }));
  const fill = h('button', { type: 'button', class: 'btn btn--sm', onclick: () => document.dispatchEvent(new CustomEvent('sensai:mock-prompt', { detail: { text: hint.textContent } })) }, t('dev.fill'));
  const reset = h('button', { type: 'button', class: 'btn btn--sm', onclick: () => { ctl.reset(); dispatchEvent(new HashChangeEvent('hashchange')); } }, t('dev.reset'));
  const exp = h('button', { type: 'button', class: 'btn btn--sm', onclick: () => download(`${ctl.state.scenario}.events.json`, JSON.stringify(exportScript(ctl.state.scenario), null, 2)) }, t('dev.export'));
  const panel = h('aside', { class: 'devpanel', role: 'region', 'aria-label': t('dev.title'), hidden: true },
    h('div', { class: 'row' }, h('strong', { class: 'grow' }, t('dev.title')), h('span', { class: 'chip chip--amber' }, t('common.mockData'))),
    scenario, hint, info, speed, inject, h('div', { class: 'row' }, fill, reset, exp));
  document.body.append(panel);
  ctl.onChange(() => { inject.querySelector('select').value = ctl.state.inject || ''; paintInfo(); });
  document.addEventListener('keydown', (e) => {
    if (hasMod(e) && e.shiftKey && e.key.toLowerCase() === 'd') { e.preventDefault(); if (!keynote()) { panel.hidden = !panel.hidden; paintInfo(); } }
  });
  document.addEventListener('sensai:route', () => { if (keynote()) panel.hidden = true; });
  paintInfo();
}
