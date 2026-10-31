// Scrolling log: autoscroll within 80 px of the bottom, jump pill, date separators, scroll-preserving prepend.
import { h } from '../dom.js';
import { icon } from '../icons.js';
import { createDate, dayKey } from './messages.js';
import { t } from '../i18n.js';

const NEAR = 80;

export function createTranscript() {
  const content = h('div', { class: 'transcript__content' });
  const scroller = h('div', { class: 'transcript', role: 'log', 'aria-live': 'off', 'aria-label': t('chat.transcript'), tabindex: '0' }, content);
  const pill = h('button', { type: 'button', class: 'btn btn--sm jump', hidden: true }, icon('chevron-down', { size: 16 }), t('chat.jump'));
  const el = h('div', { class: 'transcript-wrap' }, scroller, pill);
  let stuck = true, streaming = false, lastDay = null, empty = null;

  const toBottom = () => { scroller.scrollTop = scroller.scrollHeight; };
  scroller.addEventListener('scroll', () => {
    stuck = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight <= NEAR;
    if (stuck) pill.hidden = true;
  }, { passive: true });
  new ResizeObserver(() => { if (stuck) toBottom(); else if (streaming) pill.hidden = false; }).observe(content);
  pill.addEventListener('click', () => { stuck = true; pill.hidden = true; toBottom(); });

  return {
    el, scroller, content,
    setStreaming(on) { streaming = on; if (!on && stuck) pill.hidden = true; },
    setEmpty(node) { empty?.remove(); empty = node; if (node) content.prepend(node); },
    hasEmpty: () => !!empty?.isConnected,
    append(node, at) {
      if (empty?.isConnected) empty.remove();
      const day = dayKey(at);
      if (at && day !== lastDay) { content.append(createDate(at)); lastDay = day; }
      content.append(node);
    },
    /** Inserts older nodes at the top without moving what the reader sees. */
    prepend(nodes) {
      const before = scroller.scrollHeight;
      const first = content.firstChild;
      for (const n of nodes) content.insertBefore(n, first);
      if (!stuck) scroller.scrollTop += scroller.scrollHeight - before;
    },
    scrollToBottom: () => { stuck = true; toBottom(); },
    setLastDay: (iso) => { lastDay = dayKey(iso); },
    flash(node) {
      node.scrollIntoView({ block: 'center' });
      node.classList.add('is-flash');
      setTimeout(() => node.classList.remove('is-flash'), 1600);
    },
  };
}
