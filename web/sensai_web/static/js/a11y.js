// Focus trap, live-region announcer, roving tabindex.
let region;
export function announce(text) {
  if (!region) {
    region = document.createElement('div');
    region.className = 'sr-only';
    region.setAttribute('aria-live', 'polite');
    region.setAttribute('aria-atomic', 'true');
    document.body.append(region);
  }
  region.textContent = '';
  setTimeout(() => { region.textContent = text; }, 30);
}

const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';
const visible = (el) => el.offsetParent !== null || el === document.activeElement;

/** Traps Tab inside container and restores focus on release. Returns release(). */
export function trapFocus(container) {
  const prev = document.activeElement;
  const onKey = (e) => {
    if (e.key !== 'Tab') return;
    const els = [...container.querySelectorAll(FOCUSABLE)].filter(visible);
    if (!els.length) { e.preventDefault(); return; }
    const first = els[0], last = els[els.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  };
  container.addEventListener('keydown', onKey);
  return () => { container.removeEventListener('keydown', onKey); if (prev && prev.isConnected) prev.focus(); };
}

/** Roving tabindex over items matching selector. orientation: 'vertical' | 'horizontal' | 'both'. */
export function rovingTabindex(container, selector, { orientation = 'vertical', onActivate } = {}) {
  const items = () => [...container.querySelectorAll(selector)];
  const setActive = (el) => items().forEach((i) => i.setAttribute('tabindex', i === el ? '0' : '-1'));
  const init = () => { const l = items(); setActive(l.find((i) => i.getAttribute('aria-current') || i.getAttribute('aria-selected') === 'true') || l[0]); };
  const prev = orientation === 'horizontal' ? ['ArrowLeft'] : orientation === 'vertical' ? ['ArrowUp'] : ['ArrowUp', 'ArrowLeft'];
  const next = orientation === 'horizontal' ? ['ArrowRight'] : orientation === 'vertical' ? ['ArrowDown'] : ['ArrowDown', 'ArrowRight'];
  container.addEventListener('keydown', (e) => {
    const list = items();
    const i = list.indexOf(document.activeElement);
    if (i < 0) return;
    let to = null;
    if (next.includes(e.key)) to = list[(i + 1) % list.length];
    else if (prev.includes(e.key)) to = list[(i - 1 + list.length) % list.length];
    else if (e.key === 'Home') to = list[0];
    else if (e.key === 'End') to = list[list.length - 1];
    else if ((e.key === 'Enter' || e.key === ' ') && onActivate) { e.preventDefault(); onActivate(list[i]); return; }
    if (to) { e.preventDefault(); setActive(to); to.focus(); if (onActivate && orientation === 'horizontal') onActivate(to, true); }
  });
  container.addEventListener('focusin', (e) => { if (e.target.matches?.(selector)) setActive(e.target); });
  init();
  return { refresh: init };
}
