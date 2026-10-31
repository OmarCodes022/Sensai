import { h } from '../dom.js';

let current = null;

/** Anchored popover that flips, closes on Esc/outside click, and returns focus to the anchor. */
export function openPopover(anchor, content, { menu = false, label, onClose } = {}) {
  current?.close();
  const el = h('div', { class: `popover ${menu ? 'popover--menu' : ''}`, role: menu ? 'menu' : 'dialog', 'aria-label': label, tabindex: '-1' }, content);
  document.body.append(el);
  anchor.setAttribute('aria-expanded', 'true');
  const place = () => {
    const a = anchor.getBoundingClientRect();
    const w = el.offsetWidth, hh = el.offsetHeight;
    let left = Math.min(Math.max(8, a.left), innerWidth - w - 8);
    let top = a.bottom + 6;
    if (top + hh > innerHeight - 8 && a.top - hh - 6 > 8) top = a.top - hh - 6;
    el.style.setProperty('left', `${left}px`);
    el.style.setProperty('top', `${Math.max(8, top)}px`);
  };
  place();
  const onDoc = (e) => { if (!el.contains(e.target) && !anchor.contains(e.target)) close(); };
  const onKey = (e) => {
    if (e.key === 'Escape') { e.stopPropagation(); close(); anchor.focus(); }
    if (menu && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
      const items = [...el.querySelectorAll('[role^="menuitem"]:not([aria-disabled="true"])')];
      const i = items.indexOf(document.activeElement);
      items[(i + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length]?.focus();
      e.preventDefault();
    }
  };
  setTimeout(() => document.addEventListener('pointerdown', onDoc), 0);
  document.addEventListener('keydown', onKey, true);
  addEventListener('resize', place);
  function close() {
    if (current?.el !== el) return;
    current = null;
    document.removeEventListener('pointerdown', onDoc);
    document.removeEventListener('keydown', onKey, true);
    removeEventListener('resize', place);
    anchor.setAttribute('aria-expanded', 'false');
    el.remove();
    onClose?.();
  }
  current = { el, close };
  (el.querySelector('[role^="menuitem"], [role="option"][tabindex="0"], button, a[href], input') || el).focus();
  return { el, close, place };
}

export const closePopover = () => current?.close();
