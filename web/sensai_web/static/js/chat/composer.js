// Composer: auto-growing textarea, Send/Stop, slash menu with ghost text, Up recall, paste and privacy chips (spec 6.4).
import { h } from '../dom.js';
import { icon } from '../icons.js';
import { progressRing } from '../components/meter.js';
import { announce } from '../a11y.js';
import { createSlash } from './slash.js';
import { looksPersonal, privacyChip, pasteChip, LARGE_PASTE } from './hints.js';
import { t } from '../i18n.js';

const MAX_H = 192;

/** deps: { getUserTexts(), onSend(text), onStop(), onCommand(name), onPlanned(cmd), guardrails():boolean } */
export function createComposer(deps) {
  let locked = null, streaming = false, recall = -1, recalled = false, flashTimer;
  const ta = h('textarea', { class: 'composer__ta', rows: 1, placeholder: t('chat.placeholder'), 'aria-label': t('chat.ariaLabel'), 'aria-autocomplete': 'list', 'aria-expanded': 'false', spellcheck: 'true', enterkeyhint: 'send', id: 'composer' });
  const ghostText = h('span'), typed = h('span', { class: 'composer__typed' });
  const ghost = h('div', { class: 'composer__ghost', 'aria-hidden': 'true' }, typed, ghostText);
  const send = h('button', { type: 'submit', class: 'btn btn--primary btn--lg composer__send' }, icon('send', { size: 18 }), h('span', { class: 'btn__label' }, t('common.send')));
  const ring = progressRing(0, t('chat.budget'));
  const stop = h('button', { type: 'button', class: 'btn btn--danger btn--lg composer__stop', hidden: true, onclick: () => deps.onStop() }, ring, icon('stop', { size: 16 }), h('span', { class: 'btn__label' }, t('common.stop')));
  const chips = h('div', { class: 'composer__chips' });
  const msg = h('div', { class: 'composer__msg', role: 'status' });
  const status = h('span', { class: 'composer__hint' }, t('chat.hint'));
  const slash = createSlash({
    textarea: ta, setGhost: (g) => { ghostText.textContent = g; }, setValue: (v) => { ta.value = v; sync(); ta.focus(); },
    run: (name) => { clear(); deps.onCommand(name); }, planned: (c) => flash(t('slash.plannedMsg', { name: c.name, task: c.task })),
  });
  ta.setAttribute('aria-controls', slash.el.querySelector('[role=listbox]').id);
  const root = h('form', { class: 'composer', role: 'form', 'aria-label': t('chat.composerLabel'), novalidate: true },
    slash.el, h('div', { class: 'composer__box' }, h('div', { class: 'composer__field' }, ghost, ta), stop, send), chips, msg,
    h('div', { class: 'composer__foot' }, status, h('span', { class: 'muted' }, t('everything.local'))));

  function flash(text) {
    msg.replaceChildren(h('span', { class: 'composer__warn' }, icon('alert-triangle', { size: 14 }), text));
    announce(text); clearTimeout(flashTimer); flashTimer = setTimeout(() => msg.replaceChildren(), 5000);
  }
  function grow() {
    ta.style.setProperty('height', 'auto');
    ta.style.setProperty('height', `${Math.min(ta.scrollHeight, MAX_H)}px`);
    ta.style.setProperty('overflow-y', ta.scrollHeight > MAX_H ? 'auto' : 'hidden');
  }
  function sync() {
    typed.textContent = ta.value.startsWith('/') ? ta.value : '';
    grow(); slash.update();
    chips.querySelector('.chip--plum')?.remove();
    if (looksPersonal(ta.value)) chips.append(privacyChip(deps.guardrails()));
    send.disabled = !!locked;
  }
  const clear = () => { ta.value = ''; recall = -1; recalled = false; chips.replaceChildren(); sync(); };

  function submit() {
    const text = ta.value;
    if (locked || streaming) return;
    if (!text.trim()) return flash(t('chat.empty'));
    if (text.startsWith('/') && slash.tryRun(text)) return;
    msg.replaceChildren();
    clear();
    deps.onSend(text);
  }
  root.addEventListener('submit', (e) => { e.preventDefault(); submit(); });
  ta.addEventListener('input', () => { recalled = false; msg.replaceChildren(); sync(); });
  ta.addEventListener('keydown', (e) => {
    if (slash.key(e)) return;
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); if (streaming) announce(t('chat.waitReply')); else submit(); return; }
    if ((e.key === 'ArrowUp' || e.key === 'ArrowDown') && (ta.value === '' || recalled) && !e.shiftKey) {
      const texts = deps.getUserTexts();
      if (e.key === 'ArrowUp' && recall < texts.length - 1) recall += 1;
      else if (e.key === 'ArrowDown' && recall >= 0) recall -= 1;
      else return;
      e.preventDefault(); ta.value = recall >= 0 ? texts[texts.length - 1 - recall] : ''; recalled = recall >= 0; sync();
    }
  });
  ta.addEventListener('paste', () => {
    const before = ta.value;
    setTimeout(() => {
      const added = ta.value.length - before.length;
      if (added > LARGE_PASTE) { chips.querySelector('.chip--amber')?.remove(); chips.append(pasteChip(added, () => { ta.value = before; sync(); ta.focus(); })); }
    }, 0);
  });

  const api = {
    el: root, textarea: ta,
    focus: () => ta.focus(),
    fill(text) { ta.value = text; recalled = false; sync(); ta.focus(); ta.setSelectionRange(text.length, text.length); },
    setStreaming(on) {
      streaming = on; send.hidden = on; stop.hidden = !on;
      status.textContent = on ? '' : t('chat.hint'); if (!on) api.setRing(0);
    },
    setElapsed(text) { if (streaming) status.textContent = text; },
    setRing(pct) { ring.style.setProperty('--v', String(Math.min(100, Math.max(0, pct)))); ring.setAttribute('aria-valuenow', String(Math.round(pct))); },
    /** reason: null | offline | locked | approval | resuming. */
    setLock(reason) {
      locked = reason; ta.disabled = !!reason; send.disabled = !!reason;
      ta.placeholder = reason ? t(`chat.disabled.${reason}`) : t('chat.placeholder');
    },
    flash,
  };
  sync();
  return api;
}
