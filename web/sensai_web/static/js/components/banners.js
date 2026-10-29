import { h } from '../dom.js';
import { icon } from '../icons.js';
import { button } from './button.js';
import { t } from '../i18n.js';

/** banner({tone: info|warning|error, text, actions:[{label,onClick}]}) */
export function banner({ tone = 'info', text, actions = [], inline = false }) {
  const ic = tone === 'error' ? 'x-circle' : tone === 'warning' ? 'alert-triangle' : 'info';
  return h('div', { class: `banner banner--${tone === 'info' ? 'info' : tone} ${inline ? 'banner--inline' : ''}`, role: tone === 'error' ? 'alert' : 'status' },
    icon(ic, { size: 18 }), h('span', { class: 'banner__text' }, text), actions.map((a) => button(a.label, { size: 'sm', onClick: a.onClick })));
}

/** Banner area under the top bar: mock fallback and offline/reconnect. */
export function createBanners({ store, onReconnect, fallback }) {
  const box = h('div', { class: 'banners' });
  const paint = () => {
    const st = store.get().status, out = [];
    if (st.mock && fallback) out.push(banner({ tone: 'warning', text: t('banner.fallback') }));
    else if (st.mock) out.push(banner({ text: t('banner.mock') }));
    if (st.backend === 'offline' && !st.mock) out.push(banner({ tone: 'error', text: t('banner.offline', { s: st.retryIn ?? '...' }), actions: [{ label: t('banner.reconnect'), onClick: onReconnect }] }));
    box.replaceChildren(...out);
  };
  store.subscribe(paint, ['status']);
  document.addEventListener('sensai:lang', paint);
  paint();
  return box;
}
