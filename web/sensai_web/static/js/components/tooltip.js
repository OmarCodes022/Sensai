import { h } from '../dom.js';

/** Global tooltip for [data-tip]: 400 ms delay, shows on keyboard focus, Esc dismisses, hoverable. */
export function initTooltips() {
  let tip = null, timer = null, target = null;
  const hide = () => {
    clearTimeout(timer);
    tip?.remove();
    target?.removeAttribute('aria-describedby');
    tip = target = null;
  };
  const show = (el) => {
    hide();
    target = el;
    tip = h('div', { class: 'tooltip', role: 'tooltip', id: 'tooltip' }, el.dataset.tip);
    tip.addEventListener('pointerleave', hide);
    document.body.append(tip);
    const r = el.getBoundingClientRect();
    tip.style.setProperty('left', `${Math.min(Math.max(8, r.left + r.width / 2 - tip.offsetWidth / 2), innerWidth - tip.offsetWidth - 8)}px`);
    const below = r.bottom + 6 + tip.offsetHeight < innerHeight;
    tip.style.setProperty('top', `${below ? r.bottom + 6 : r.top - tip.offsetHeight - 6}px`);
    el.setAttribute('aria-describedby', 'tooltip');
  };
  const arm = (e) => {
    const el = e.target.closest?.('[data-tip]');
    if (!el || el === target) return;
    clearTimeout(timer);
    timer = setTimeout(() => show(el), e.type === 'focusin' ? 0 : 400);
  };
  document.addEventListener('pointerover', arm);
  document.addEventListener('focusin', arm);
  document.addEventListener('pointerout', (e) => { if (e.target.closest?.('[data-tip]') && !tip?.matches(':hover')) setTimeout(() => { if (!tip?.matches(':hover')) hide(); }, 80); });
  document.addEventListener('focusout', hide);
  document.addEventListener('pointerdown', hide);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && tip) { hide(); } });
}
