import { h } from '../dom.js';
import { visibleEscapes } from '../safetext.js';
import { copyButton } from './copy-button.js';
import { t } from '../i18n.js';

/** Code block: header (language, wrap toggle, copy), scrollable body max 480 px with Show all. */
export function codeBlock(text, lang = '') {
  const pre = h('pre', { class: 'code', tabindex: '0' });
  const code = h('code');
  code.append(visibleEscapes(text));
  pre.append(code);
  pre.style.setProperty('max-height', '480px');
  const wrap = h('button', { type: 'button', class: 'btn btn--ghost btn--sm', 'aria-pressed': 'false' }, t('code.wrap'));
  wrap.addEventListener('click', () => {
    const on = wrap.getAttribute('aria-pressed') !== 'true';
    wrap.setAttribute('aria-pressed', String(on));
    pre.style.setProperty('white-space', on ? 'pre-wrap' : 'pre');
  });
  const more = h('button', { type: 'button', class: 'btn btn--ghost btn--sm', hidden: true }, t('code.showAll'));
  more.addEventListener('click', () => { pre.style.setProperty('max-height', 'none'); more.hidden = true; });
  pre.addEventListener('keydown', (e) => { if (e.key === 'Escape') pre.blur(); }); // do not trap keyboard users
  const head = h('div', { class: 'row codeblock__head' }, h('span', { class: 'chip chip--mono' }, lang || t('code.plain')), h('span', { class: 'grow' }), wrap, more, copyButton(() => text, { label: t('common.copy') }));
  const box = h('figure', { class: 'codeblock' }, head, pre);
  queueMicrotask(() => requestAnimationFrame(() => { more.hidden = pre.scrollHeight <= 480; }));
  return box;
}
