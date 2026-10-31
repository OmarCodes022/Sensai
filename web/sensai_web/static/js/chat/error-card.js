// Error cards (spec 6.10): one table-driven card for every backend error code.
import { h } from '../dom.js';
import { icon } from '../icons.js';
import { copyButton } from '../components/copy-button.js';
import { formatUtc } from '../format.js';
import { stripInvisible } from '../safetext.js';
import { t } from '../i18n.js';

/** Action ids per code. Copy details is always present. */
const ACTIONS = {
  connection: ['hint', 'retry', 'status'], model_not_found: ['hint', 'retry'], timeout: ['retry'], turn_timeout: ['retry', 'settings'],
  llm_error: ['retry'], invalid_response: ['retry'], storage: ['dismiss'], profile_invalid: ['profile'], persona_unknown: ['personas'],
  tab_locked: ['takeover'], network: ['reconnect'], guardrail_refused: [],
};

const bodyFor = (e) => {
  const m = stripInvisible(e.message || '');
  if (e.code === 'turn_timeout') return t('errb.turn_timeout', { s: e.seconds ?? 120 });
  if (e.code === 'network') return t('errb.network');
  if (e.code === 'storage') return [m, ' ', t('errb.storage')].join('');
  if (e.code === 'guardrail_refused') return [e.reason, m].filter(Boolean).join(': ');
  return m || t(`errb.${e.code}`);
};

/** err: {code,message,hint,status,seconds,reason}. handlers: { retry, reconnect, takeover, goto(path), openStatus, dismiss } */
export function createErrorCard(err, handlers = {}) {
  const code = ACTIONS[err.code] ? err.code : 'llm_error';
  const at = new Date().toISOString();
  const title = ACTIONS[err.code] ? t(`err.${err.code}`) : t('err.generic');
  const detailText = [`code: ${err.code}`, `http: ${err.status || t('common.na')}`, `time: ${at}`, `message: ${err.message || ''}`, err.hint ? `hint: ${err.hint}` : ''].filter(Boolean).join('\n');
  const btn = (label, fn, cls = '') => h('button', { type: 'button', class: `btn btn--sm ${cls}`, onclick: fn }, label);
  const make = {
    hint: () => (err.hint ? copyButton(() => err.hint, { label: t('common.copyCommand'), text: true }) : null),
    retry: () => (handlers.retry ? btn(t('common.retry'), handlers.retry, 'btn--primary') : null),
    status: () => btn(t('err.openStatus'), () => handlers.openStatus?.()),
    settings: () => btn(t('nav.settings'), () => handlers.goto?.('#/settings')),
    profile: () => btn(t('err.editProfile'), () => handlers.goto?.('#/profile')),
    personas: () => btn(t('err.openPersonas'), () => handlers.goto?.('#/personas')),
    takeover: () => btn(t('lock.takeover'), () => handlers.takeover?.(), 'btn--primary'),
    reconnect: () => btn(t('banner.reconnect'), () => handlers.reconnect?.(), 'btn--primary'),
    dismiss: () => btn(t('common.dismiss'), () => el.remove()),
  };
  const actions = (ACTIONS[code]).map((a) => make[a]()).filter(Boolean);
  const el = h('section', { class: 'errcard', role: 'alert', dataset: { code: err.code }, tabindex: '-1' },
    h('span', { class: 'errcard__icon' }, icon(err.code === 'guardrail_refused' ? 'shield' : 'alert-triangle', { size: 20 })),
    h('div', { class: 'stack errcard__main' }, h('h3', null, title),
      h('p', { class: ['llm_error', 'invalid_response'].includes(err.code) ? 'mono' : '', dir: 'auto' }, bodyFor(err)),
      h('div', { class: 'row' }, actions, copyButton(() => detailText, { label: t('common.copyDetails'), text: true })),
      h('details', { class: 'errcard__details' }, h('summary', null, t('err.details')),
        h('dl', { class: 'kv' }, h('dt', null, t('err.code')), h('dd', { class: 'mono' }, err.code), h('dt', null, t('err.http')), h('dd', null, err.status || t('common.na')),
          h('dt', null, t('err.time')), h('dd', null, formatUtc(at)), err.hint ? [h('dt', null, t('err.hint')), h('dd', { class: 'mono' }, err.hint)] : null))));
  return { el, code: err.code };
}
