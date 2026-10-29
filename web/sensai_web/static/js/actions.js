// Shell actions shared by top bar, sidebar, palette and key bindings.
import { applyPrefs, savePrefs, resetPrefs } from './prefs.js';
import { setLang, t } from './i18n.js';
import { toast } from './components/toast.js';
import { copyText } from './components/copy-button.js';
import { confirmDialog } from './components/modal.js';
import { announce } from './a11y.js';

export function createActions({ store, api, router }) {
  const setStatus = (patch) => store.set({ status: { ...store.get().status, ...patch } });

  const actions = {
    setStatus,
    async refreshSessions({ silent = false } = {}) {
      if (!silent) store.set({ sessions: { ...store.get().sessions, state: 'loading' } });
      try { store.set({ sessions: { items: (await api.sessions()).items, state: 'idle' } }); }
      catch { store.set({ sessions: { ...store.get().sessions, state: 'error' } }); }
    },
    async newChat() {
      if (store.get().status.streaming && !(await actions.confirmStop())) return;
      try {
        store.set({ session: await api.newSession() });
        router.go('#/chat');
        document.dispatchEvent(new CustomEvent('sensai:session-changed'));
      } catch (e) { toast(e.message, { tone: 'rose' }); }
    },
    /** Asks before leaving a streaming turn. Chat view listens for sensai:stop-request. */
    async confirmStop() {
      const ok = await confirmDialog({ title: t('sessions.switchTitle'), message: t('sessions.switchMessage'), confirmLabel: t('sessions.stopSwitch'), cancelLabel: t('sessions.stay') });
      if (ok) document.dispatchEvent(new CustomEvent('sensai:stop-request'));
      return ok;
    },
    async setPersona(id) {
      const s = store.get();
      if (s.status.streaming || id === s.activePersona) return;
      try {
        await api.setPersona(id);
        const name = s.personas.find((p) => p.id === id)?.name || id;
        store.set({ activePersona: id });
        document.dispatchEvent(new CustomEvent('sensai:persona-changed', { detail: { id, name } }));
        toast(t('persona.toast', { name })); announce(t('persona.toast', { name }));
      } catch (e) { toast(e.message, { tone: 'rose' }); }
    },
    /** Create or edit a persona; throws the backend message so the editor can show it. */
    async savePersona(id, data) {
      const r = await api.savePersona(id, data);
      store.set({ personas: r.items, activePersona: r.active ?? store.get().activePersona });
      toast(t('personas.saved', { name: data.name })); announce(t('personas.saved', { name: data.name }));
    },
    async deletePersona(id) {
      const r = await api.deletePersona(id);
      store.set({ personas: r.items, activePersona: r.active ?? store.get().activePersona });
      toast(t('personas.removed')); announce(t('personas.removed'));
    },
    async setModel(name) {
      if (store.get().status.streaming) { toast(t('persona.waitTip'), { tone: 'rose' }); return; }
      try {
        const { model } = await api.setModel(name);
        const s = store.get();
        store.set({ config: { ...s.config, model }, status: { ...s.status, health: { ...s.status.health, model: { name: model, available: true } } } });
        toast(t('status.modelSet', { name: model })); announce(t('status.modelSet', { name: model }));
      } catch (e) { toast(e.message, { tone: 'rose' }); }
    },
    async copySessionId() {
      const id = store.get().session?.id;
      if (id && await copyText(id)) { toast(t('session.idCopied')); announce(t('session.idCopied')); }
    },
    setPref(key, value) {
      const prefs = { ...store.get().prefs, [key]: value };
      store.set({ prefs });
      savePrefs(prefs);
      applyPrefs(prefs);
      if (key === 'lang') setLang(value).then(() => document.dispatchEvent(new CustomEvent('sensai:lang')));
    },
    cycleTheme() {
      const order = ['system', 'light', 'dark'];
      const cur = store.get().prefs.theme;
      actions.setPref('theme', order[(order.indexOf(cur) + 1) % 3]);
    },
    resetPrefs() {
      const prefs = resetPrefs();
      store.set({ prefs });
      applyPrefs(prefs);
      setLang(prefs.lang).then(() => document.dispatchEvent(new CustomEvent('sensai:lang')));
    },
  };
  return actions;
}
