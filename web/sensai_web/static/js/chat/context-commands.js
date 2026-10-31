// /context and /compact (M2), run in the page: the window, the last count, and summarizing older messages now.
import { h } from '../dom.js';
import { meter } from '../components/meter.js';
import { formatNumber } from '../format.js';
import { announce } from '../a11y.js';
import { t } from '../i18n.js';

/** deps: { api, store, transcript }. Returns { context, compact }. */
export function createContextCommands({ api, store, transcript }) {
  const show = (node) => { transcript.append(node, new Date().toISOString()); transcript.scrollToBottom(); };
  const card = (title, ...kids) => h('section', { class: 'card stack doccmd', role: 'status' }, h('strong', null, title), ...kids);
  const fail = (e) => show(card(t('doccmd.failed'), h('p', { class: 'field__error', role: 'alert' }, e.message)));

  function report(c) {
    return h('dl', { class: 'kv' },
      h('dt', null, t('context.window')), h('dd', { class: 'num' }, `${formatNumber(c.budget)} (${t(`context.source.${c.source}`)})`),
      h('dt', null, t('context.lastTurn')), h('dd', { class: 'num' }, c.last_tokens == null ? t('common.na') : formatNumber(c.last_tokens)),
      h('dt', null, t('context.summaries')), h('dd', { class: 'num' }, formatNumber(c.summaries)),
      h('dt', null, t('context.saved')), h('dd', { class: 'num' }, formatNumber(c.saved)));
  }

  async function context() {
    try {
      const c = await api.context();
      store.set({ context: c });
      show(card(t('context.title'), c.last_tokens == null ? null : meter({ value: c.last_tokens, max: c.budget, marker: true }), report(c),
        h('p', { class: 'muted' }, t('context.hint', { pct: Math.round(c.threshold * 100) }))));
    } catch (e) { fail(e); }
  }

  async function compact() {
    try {
      const c = await api.compactContext();
      store.set({ context: c });
      const text = t('context.compacted', { before: formatNumber(c.before), after: formatNumber(c.after) });
      announce(text);
      show(card(text, h('p', { class: 'muted' }, t('context.compactedBody', { n: c.messages }))));
      api.session().then((s) => store.set({ session: s })).catch(() => {});
    } catch (e) { fail(e); }
  }

  return { context, compact };
}
