// Public links (X3) on the Campaign page: the exact page and URL are shown, nothing is published before Share.
import { h } from '../dom.js';
import { button } from '../components/button.js';
import { chip } from '../components/chip.js';
import { toast } from '../components/toast.js';
import { announce } from '../a11y.js';
import { t } from '../i18n.js';

const SHAREABLE = ['posts', 'report', 'calendar'];

/** deps: { api, out } where `out` shows the confirm card. Returns { button(section), list }. */
export function createShare({ api, out }) {
  const list = h('div', { class: 'stack' });

  function paintList(d) {
    list.replaceChildren(...(d.items.length ? [h('h3', null, t('share.links')), ...d.items.map((s) => h('div', { class: 'row card' },
      h('code', { class: 'mono grow' }, s.url), button(t('share.remove'), { size: 'sm', icon: 'trash', onClick: () => remove(s.token) })))] : []),
      h('p', { class: 'muted' }, t('share.serve', { port: d.port })));
  }

  async function remove(token) {
    try { paintList(await api.unshare(token)); toast(t('share.removed')); announce(t('share.removed')); } catch (e) { toast(e.message, { tone: 'rose' }); }
  }

  async function propose(section) {
    try {
      const p = await api.share(section);
      const decide = async (ok) => {
        try {
          const r = await api.shareConfirm(p.token, ok);
          paintList(r);
          out.replaceChildren(h('p', { class: 'muted', role: 'status' }, ok ? t('share.done', { url: r.url }) : t('share.nothing')));
          announce(ok ? t('share.done', { url: r.url }) : t('share.nothing'));
        } catch (e) { out.replaceChildren(h('p', { class: 'field__error', role: 'alert' }, e.message)); }
      };
      out.replaceChildren(h('div', { class: 'card approval-mini stack', role: 'group', 'aria-label': t('share.question') },
        h('div', { class: 'row' }, h('b', null, t('share.question')), chip(t('share.public'), { tone: 'amber', icon: 'link' })),
        h('p', null, t('share.where'), ': ', h('code', null, p.url)),
        h('div', { class: 'muted' }, t('share.content')), h('div', { class: 'diff diff--add code--wrap', dir: 'auto' }, p.content),
        h('div', { class: 'row' }, button(`${t('common.refuse')} (n)`, { onClick: () => decide(false) }),
          button(`${t('share.confirm')} (y)`, { variant: 'primary', icon: 'link', onClick: () => decide(true) }))));
    } catch (e) { out.replaceChildren(h('p', { class: 'field__error', role: 'alert' }, e.message)); }
  }

  api.shares().then(paintList).catch(() => {});
  return { button: (section) => (SHAREABLE.includes(section) ? button(t('share.button'), { icon: 'link', onClick: () => propose(section) }) : null), list };
}
