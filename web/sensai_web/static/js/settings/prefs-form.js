// UI preferences (stored in this browser only). Every control writes through actions.setPref.
import { h } from '../dom.js';
import { segmented, toggle } from '../components/form.js';
import { button } from '../components/button.js';
import { confirmDialog } from '../components/modal.js';
import { toast } from '../components/toast.js';
import { t } from '../i18n.js';

export function prefsForm({ store, actions }) {
  const p = store.get().prefs;
  const seg = (key, label, opts) => h('div', { class: 'stack' }, h('span', { class: 'field__label' }, label),
    segmented(label, opts.map(([v, l]) => [v, l]), p[key], (v) => actions.setPref(key, v)));
  const tog = (key, label) => toggle(label, { checked: !!p[key], onChange: (v) => actions.setPref(key, v) });
  return h('div', { class: 'stack' },
    h('p', { class: 'muted' }, t('settings.prefsNote')),
    seg('theme', t('settings.theme'), [['system', t('theme.system')], ['light', t('theme.light')], ['dark', t('theme.dark')]]),
    seg('density', t('settings.density'), [['comfortable', t('settings.comfortable')], ['compact', t('settings.compact')]]),
    seg('fontSize', t('settings.fontSize'), [['small', t('settings.small')], ['default', t('settings.default')], ['large', t('settings.large')], ['keynote', t('nav.keynote')]]),
    seg('motion', t('settings.motion'), [['system', t('theme.system')], ['reduce', t('settings.reduce')]]),
    seg('lang', t('settings.lang'), [['en', 'English'], ['fr', 'Français']]),
    tog('showTokens', t('settings.showTokens')), tog('showTools', t('settings.showTools')), tog('showNumbers', t('settings.showNumbers')), tog('draftLabel', t('settings.draftLabel')),
    h('div', null, button(t('settings.reset'), { variant: 'danger', onClick: async () => {
      if (await confirmDialog({ title: t('settings.reset'), message: t('settings.resetBody'), confirmLabel: t('settings.reset'), danger: true })) { actions.resetPrefs(); toast(t('settings.resetDone')); }
    } })));
}
