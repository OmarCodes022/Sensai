// Presenter bar: scenario picker, play/pause/step/restart, speed, beat timeline, notes. Lives on <body> across routes.
import { h } from '../dom.js';
import { icon } from '../icons.js';
import { iconButton } from '../components/button.js';
import { chip } from '../components/chip.js';
import { select } from '../components/form.js';
import { progressBar } from '../components/meter.js';
import { control } from '../mock/mock-api.js';
import { playable, promptFor, notesOf } from './beats.js';
import { byId } from '../mock/scenarios.js';
import { t } from '../i18n.js';

let bar = null;

export const keynoteActive = () => !!bar;

export function stopKeynote() {
  bar?.dispose();
  bar = null;
}

export function startKeynote({ scenarioId, router, store, record }) {
  stopKeynote();
  document.body.classList.add('keynote');
  document.body.classList.toggle('keynote-record', !!record);
  let sc = control.select(scenarioId), playing = false, timer = null, notesOn = false;
  const beats = () => sc.turns.length;
  const idx = () => Math.min(control.state.turnIdx, beats());

  const picker = select(playable().map((s) => [s.id, `${s.n}. ${s.title}`]), { 'aria-label': t('keynote.scenario') });
  picker.value = sc.id;
  const play = iconButton('play', t('keynote.play'), { variant: 'primary', 'aria-pressed': 'false' });
  const step = iconButton('chevron-right', t('keynote.step'));
  const restart = iconButton('refresh', t('keynote.restart'));
  const exit = iconButton('x', t('keynote.exit'));
  const speed = h('input', { type: 'range', min: 0.5, max: 3, step: 0.25, value: 1, 'aria-label': t('keynote.speed'), 'aria-valuetext': '1x' });
  const speedText = h('span', { class: 'num', 'aria-hidden': 'true' }, '1x');
  const timeline = h('ol', { class: 'beats', 'aria-label': t('keynote.timeline') });
  const progress = h('div', { class: 'beats__bar' });
  const notes = h('aside', { class: 'keynote-notes card', 'aria-label': t('keynote.notes'), hidden: true });
  const notesBtn = h('button', { type: 'button', class: 'btn btn--sm', 'aria-pressed': 'false', 'aria-keyshortcuts': 'N' }, t('keynote.notes'));
  const live = h('span', { class: 'sr-only', role: 'status' });
  const el = h('section', { class: 'presenter', 'aria-label': t('keynote.bar') },
    h('div', { class: 'row' }, picker, play, step, restart, h('label', { class: 'row' }, h('span', { class: 'muted' }, t('keynote.speed')), speed, speedText), notesBtn,
      store.get().status.mock ? chip(t('keynote.fallback'), { tone: 'amber', icon: 'info' }) : null, h('span', { class: 'grow' }), exit), progress, timeline, live);
  document.body.append(el, notes);

  function paint() {
    const i = idx(), n = beats();
    timeline.replaceChildren(...sc.turns.map((_, k) => h('li', { class: k < i ? 'is-done' : k === i ? 'is-next' : '', 'aria-current': k === i && i < n ? 'step' : null, title: promptFor(sc, k) }, `${k + 1}`)));
    progress.replaceChildren(progressBar(n ? (i / n) * 100 : 0), h('span', { class: 'muted num' }, t('keynote.beat', { i: Math.min(i + 1, n), n })));
    play.setAttribute('aria-pressed', String(playing));
    play.setAttribute('aria-label', playing ? t('keynote.pause') : t('keynote.play'));
    play.replaceChildren(icon(playing ? 'pause' : 'play', { size: 18 }));
    step.disabled = i >= n;
    const list = notesOf(sc);
    notes.replaceChildren(h('h2', null, t('keynote.notes')), h('p', { class: 'mono' }, i < n ? promptFor(sc, i) : t('keynote.done')),
      list.length ? h('ol', { class: 'bullets' }, list.map((x) => h('li', null, x))) : h('p', { class: 'muted' }, t('keynote.noNotes')));
    notes.hidden = !notesOn;
    notesBtn.setAttribute('aria-pressed', String(notesOn));
  }

  async function toChat() {
    if (router.current?.name === 'chat') return;
    router.go('#/chat');
    await new Promise((r) => document.addEventListener('sensai:route', r, { once: true }));
    await new Promise((r) => setTimeout(r, 400));
  }
  async function next() {
    if (store.get().status.streaming || idx() >= beats()) return;
    await toChat();
    document.dispatchEvent(new CustomEvent('sensai:mock-prompt', { detail: { text: promptFor(sc, idx()) } }));
    document.querySelector('form.composer')?.requestSubmit();
    live.textContent = t('keynote.beat', { i: idx() + 1, n: beats() });
  }
  function tick() {
    clearTimeout(timer);
    if (playing && !store.get().status.streaming && !document.querySelector('.approval, dialog[open]')) {
      if (idx() >= beats()) { playing = false; paint(); return; }
      next();
    }
    if (playing) timer = setTimeout(tick, 1800);
  }
  const reset = async (id) => {
    playing = false; clearTimeout(timer); sc = control.select(id || sc.id); picker.value = sc.id;
    if (router.current?.name === 'chat') router.refresh(); else router.go('#/chat');
    paint();
  };
  picker.addEventListener('change', () => reset(picker.value));
  play.addEventListener('click', () => { playing = !playing; paint(); if (playing) tick(); else clearTimeout(timer); });
  step.addEventListener('click', () => { playing = false; clearTimeout(timer); next(); paint(); });
  restart.addEventListener('click', () => reset());
  exit.addEventListener('click', () => { stopKeynote(); router.go('#/keynote'); });
  speed.addEventListener('input', () => {
    const v = Number(speed.value);
    speedText.textContent = `${v}x`; speed.setAttribute('aria-valuetext', `${v}x`);
    control.set({ speed: 1 / v });
  });
  notesBtn.addEventListener('click', () => { notesOn = !notesOn; paint(); });
  const onKey = (e) => { if (e.key.toLowerCase() === 'n' && !e.ctrlKey && !e.metaKey && !e.altKey && !e.target.matches?.('input,textarea,select,[contenteditable]')) { notesOn = !notesOn; paint(); } };
  const unsub = [control.onChange(paint), store.subscribe(() => { if (playing) { clearTimeout(timer); timer = setTimeout(tick, 1800); } paint(); }, ['status', 'session'])];
  document.addEventListener('keydown', onKey);
  paint();
  bar = { dispose() { clearTimeout(timer); document.removeEventListener('keydown', onKey); unsub.forEach((f) => f()); el.remove(); notes.remove(); document.body.classList.remove('keynote', 'keynote-record'); control.set({ speed: 'normal' }); } };
  reset(sc.id);
}
