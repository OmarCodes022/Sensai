// Options shared by live and restored assistant messages.
import { personaTone } from '../components/topbar.js';
import { toast } from '../components/toast.js';
import { t } from '../i18n.js';

/** Resolves a persona id (or name) into the props createAssistant needs. */
export function assistantOptions(ctx, personaId) {
  const { store, layout } = ctx;
  const s = store.get();
  const idx = s.personas.findIndex((p) => p.id === personaId || p.name === personaId);
  const persona = s.personas[idx] || { id: personaId, name: personaId || '' };
  return {
    persona, tone: personaTone(Math.max(0, idx)),
    draft: (s.config?.draft_personas || ['redaction', 'communaute']).includes(persona.id) && s.prefs.draftLabel !== false,
    onDetails(usage) { store.set({ selectedTurn: usage || {} }); layout.openInspector(); document.querySelector('.inspector')?.select?.('turn'); },
    onCite(n, sources) {
      const src = sources?.find((x) => x.n === n);
      toast(src ? t('chat.source', { n, source: src.source, version: src.version ?? t('common.na') }) : t('chat.sourceNone', { n }));
    },
  };
}
