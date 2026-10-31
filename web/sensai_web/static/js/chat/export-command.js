// /export in the chat (X3, private): the conversation and the week's campaign written to exports/ on this computer.
import { h } from '../dom.js';
import { t } from '../i18n.js';

/** One line per export: the files written, the guardrails' refusal, or the write error. */
export function exportLine(name, r) {
  if (r.files) return h('p', null, h('strong', null, name), ': ', ...r.files.flatMap((f, i) => [i ? ', ' : '', h('code', null, f)]));
  if (r.refused) return h('p', { class: 'field__error' }, t('export.refused', { name, reason: r.refused }));
  if (r.error) return h('p', { class: 'field__error' }, r.error);
  return h('p', { class: 'muted' }, t('export.noCampaign'));
}

export function createExportCommand({ api, transcript }) {
  const show = (node) => { transcript.append(node, new Date().toISOString()); transcript.scrollToBottom(); };
  return async function exportAll() {
    try {
      const r = await api.exportAll();
      show(h('section', { class: 'card stack doccmd', role: 'status' }, h('strong', null, t('export.title')),
        exportLine(t('export.conversation'), r.conversation), exportLine(t('export.campaign'), r.campaign),
        h('p', { class: 'muted' }, t('export.private'))));
    } catch (e) { show(h('section', { class: 'card stack doccmd', role: 'alert' }, h('strong', null, t('export.failed')), h('p', { class: 'field__error' }, e.message))); }
  };
}
