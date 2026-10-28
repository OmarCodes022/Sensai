import { h } from '../dom.js';
import { icon } from '../icons.js';

/** button(label, {variant: primary|ghost|danger|secondary, size: sm|lg, icon, loading, onClick, ...attrs}) */
export function button(label, { variant = 'secondary', size, icon: ic, loading, disabled, onClick, pill, ...attrs } = {}) {
  const cls = ['btn', variant !== 'secondary' && `btn--${variant}`, size && `btn--${size}`, pill && 'btn--pill'].filter(Boolean).join(' ');
  const b = h('button', { type: 'button', class: cls, disabled, 'aria-busy': loading ? 'true' : null, ...attrs },
    loading ? h('span', { class: 'spinner', 'aria-hidden': 'true' }) : ic ? icon(ic, { size: size === 'sm' ? 16 : 18 }) : null,
    label ? h('span', { class: 'btn__label' }, label) : null);
  if (onClick) b.addEventListener('click', onClick);
  return b;
}

/** Icon-only button; the accessible name doubles as the tooltip. */
export function iconButton(name, label, { variant = 'secondary', size, onClick, ...attrs } = {}) {
  const b = button(null, { variant, size, icon: name, 'aria-label': label, 'data-tip': label, onClick, ...attrs });
  b.classList.add('btn--icon');
  return b;
}
