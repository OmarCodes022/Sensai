// Slash menu: filtering, arrows, Tab completion with ghost text, Enter to pick, Esc to close. Focus stays in the textarea.
import { h, nextId } from '../dom.js';
import { chip } from '../components/chip.js';
import { matchCommands, findCommand } from './commands.js';
import { t } from '../i18n.js';

/** deps: { textarea, run(name), planned(cmd), setGhost(text), setValue(v) }. */
export function createSlash({ textarea, run, planned, setGhost, setValue, caps = () => ({}) }) {
  const id = nextId('slash');
  const list = h('div', { class: 'slash__list', role: 'listbox', id, 'aria-label': t('slash.label') });
  const el = h('div', { class: 'slash', hidden: true }, list, h('div', { class: 'slash__foot' }, ...['move', 'complete', 'pick', 'close'].map((k) => h('span', null, t(`slash.foot.${k}`)))));
  let shown = [], active = -1, open = false, dismissed = false;

  const setOpen = (on) => {
    open = on; el.hidden = !on;
    textarea.setAttribute('aria-expanded', String(on));
    if (!on) { textarea.removeAttribute('aria-activedescendant'); setGhost(''); }
  };
  const selectable = (i) => shown[i]?.live;
  const paint = () => {
    const typed = textarea.value.slice(1);
    list.replaceChildren(...(shown.length ? shown.map((c, i) => h('div', { class: 'slash__opt', role: 'option', id: `${id}-${i}`, 'aria-selected': String(i === active), 'aria-disabled': c.live ? null : 'true', dataset: { i } },
      h('b', { class: 'mono' }, `/${c.name}`), h('span', { class: 'grow muted' }, t(`slash.${c.name}`)), c.live ? null : chip(`${t('common.planned')} ${c.task}`, { outline: true }))) : [h('p', { class: 'slash__none muted', role: 'status' }, t('slash.none'))]));
    if (active >= 0) { textarea.setAttribute('aria-activedescendant', `${id}-${active}`); list.children[active]?.scrollIntoView({ block: 'nearest' }); } else textarea.removeAttribute('aria-activedescendant');
    const c = shown[active];
    setGhost(c && c.name.startsWith(typed.toLowerCase()) && typed ? c.name.slice(typed.length) : (c && !typed ? c.name : ''));
  };
  const pick = (c, args = '') => {
    if (!c) return;
    if (!c.live) return planned(c);
    setOpen(false); run(c.name, args);
  };
  const move = (dir) => {
    const live = shown.map((c, i) => i).filter(selectable);
    if (!live.length) return;
    const at = live.indexOf(active);
    active = live[(at + dir + live.length) % live.length];
    paint();
  };

  list.addEventListener('pointerdown', (e) => { e.preventDefault(); const o = e.target.closest('.slash__opt'); if (o) pick(shown[Number(o.dataset.i)]); });

  return {
    el,
    isOpen: () => open,
    /** Call on every input event. */
    update() {
      const v = textarea.value;
      if (!/^\/[a-z]*$/i.test(v)) { dismissed = false; return setOpen(false); }
      if (dismissed) return;
      shown = matchCommands(v.slice(1), caps());
      active = shown.findIndex((c) => c.live);
      setOpen(true); paint();
    },
    /** Returns true when the key was consumed. */
    key(e) {
      if (!open) return false;
      if (e.key === 'ArrowDown') { e.preventDefault(); move(1); return true; }
      if (e.key === 'ArrowUp') { e.preventDefault(); move(-1); return true; }
      if (e.key === 'Tab' && !e.shiftKey) {
        const c = shown[active];
        if (c?.live) { e.preventDefault(); setValue(`/${c.name} `); setOpen(false); return true; }
        return false;
      }
      if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); if (active >= 0) pick(shown[active]); return true; }
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); dismissed = true; setOpen(false); return true; }
      return false;
    },
    /** Enter on a typed command with arguments, e.g. "/persona analyse". Returns true if handled. */
    tryRun(text) {
      const m = text.match(/^\/([a-z]+)(?:\s+([\s\S]*))?$/i);
      if (!m || dismissed) return false;
      const c = findCommand(m[1], caps());
      if (!c) return false;
      pick(c, (m[2] || '').trim());
      return true;
    },
  };
}
