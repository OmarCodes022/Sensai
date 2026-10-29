// Header shown only in print: session title, ID and date (spec 15).
import { h } from '../dom.js';
import { formatDate } from '../format.js';
import { stripInvisible } from '../safetext.js';
import { t } from '../i18n.js';

export function createPrintHead(store) {
  const el = h('header', { class: 'print-head' });
  const paint = () => {
    const s = store.get().session;
    el.replaceChildren(h('h1', null, s?.title ? stripInvisible(s.title) : t('session.new')), h('p', null, `${s?.id || ''} · ${formatDate(s?.updated_at || new Date().toISOString())}`));
  };
  paint();
  return { el, paint, unsub: store.subscribe(paint, ['session']) };
}
