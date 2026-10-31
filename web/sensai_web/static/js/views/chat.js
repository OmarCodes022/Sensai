// Conversation view (spec 6): transcript, composer, turn handling, slash commands and transcript menu.
import { h } from '../dom.js';
import { createTranscript } from '../chat/transcript.js';
import { createComposer } from '../chat/composer.js';
import { createTurn } from '../chat/turn.js';
import { createEmpty } from '../chat/empty.js';
import { createReconnect } from '../chat/reconnect.js';
import { createRestorer } from '../chat/restore.js';
import { createMenu } from '../chat/menu.js';
import { createDocCommands } from '../chat/doc-commands.js';
import { createEvent } from '../chat/messages.js';
import { openHistory } from '../chat/history.js';
import { createPrintHead } from '../chat/print-head.js';
import { openShortcuts } from '../components/shortcuts.js';
import { showLock } from '../components/lock.js';
import { errorState, skeletonRows } from '../components/state.js';
import { toast } from '../components/toast.js';
import { formatDate } from '../format.js';
import { stripInvisible } from '../safetext.js';
import { t } from '../i18n.js';

export function mount(root, ctx) {
  const { store, api, actions, router, layout, params } = ctx;
  const model = { items: [], dropped: [] };
  let name = '', restored = null, disposed = false;

  const transcript = createTranscript();
  const empty = createEmpty({ store, getName: () => name, onStarter: (text) => composer.fill(text) });
  const reconnect = createReconnect({ api, actions, onRestored: () => load({ keep: true }) });
  const jump = (n) => {
    restored?.flush();
    const target = transcript.content.querySelector(`[data-n="${n}"]`);
    if (target) transcript.flash(target); else toast(t('chat.noSuchMessage', { n }));
  };
  // Edit a message in place (X2): sending continues from it as a new conversation (/edit N).
  const onEdit = store.get().capabilities.branching ? (item, text) => turn.send(`/edit ${item.n} ${text}`) : null;
  const restorer = createRestorer({ ctx, onReuse: (text) => composer.fill(text), onEdit });

  const docCommands = createDocCommands({ api, transcript, router });
  const commands = {
    persona: () => document.querySelector('.persona-pill')?.click(),
    history: () => openHistory(composer.textarea, { api, canEdit: !!store.get().capabilities.branching, onPick: jump }),
    tools: () => { layout.openInspector(); document.querySelector('.inspector')?.select?.('tools'); },
    run: () => router.go('#/tools'),
    think: (args) => (args ? turn.send(`/think ${args}`) : toast(t('slash.thinkUsage'))),
    edit: (args) => (/^\d+\s+\S/.test(args || '') ? turn.send(`/edit ${args}`) : toast(t('slash.editUsage'))),
    new: () => actions.newChat(),
    help: () => openShortcuts(),
    docs: (args) => docCommands.docs(args),
    add: () => docCommands.add(),
    remove: (args) => docCommands.remove(args),
    reindex: () => docCommands.reindex(),
  };
  const composer = createComposer({
    getUserTexts: () => model.items.filter((i) => i.kind === 'user').map((i) => i.text),
    onSend: (text) => turn.send(text), onStop: () => turn.interrupt(), onCommand: (n, args) => commands[n]?.(args), onAttach: (kind) => docCommands.attach(kind), capabilities: () => store.get().capabilities,
    guardrails: () => !!store.get().capabilities.guardrails,
  });
  const turn = createTurn({ ctx, transcript, composer, model, reconnect, onReuse: (text) => composer.fill(text), onEdit });

  const bar = h('div', { class: 'chat__bar' }, h('span', { class: 'grow' }), createMenu({ store, actions, model, jump }));
  const printHead = createPrintHead(store);
  const view = h('div', { class: 'chat' }, printHead.el, h('h1', { class: 'sr-only' }, t('chat.title')), bar, transcript.el, reconnect.el, composer.el);
  root.append(view);

  const paintPrefs = () => {
    const p = store.get().prefs;
    view.dataset.tools = String(p.showTools); view.dataset.tokens = String(p.showTokens); view.dataset.numbers = String(p.showNumbers);
  };
  paintPrefs();

  async function load({ keep = false } = {}) {
    composer.setLock('resuming');
    if (!keep) transcript.setEmpty(skeletonRows(3));
    try {
      let s;
      const cur = store.get().session;
      const resuming = params.id && params.id !== cur?.id;
      if (resuming) { s = await api.resume(params.id); if (!s?.items) s = await api.getSession(params.id); } else s = await api.session();
      if (disposed) return;
      store.set({ session: s, activePersona: s.persona ?? store.get().activePersona });
      document.title = s.title ? `${stripInvisible(s.title)} - Sensai` : 'Sensai';
      model.items = [...(s.items || [])]; model.dropped = [];
      transcript.content.replaceChildren(); transcript.setEmpty(null);
      restored?.cancel();
      if (!model.items.length) transcript.setEmpty(empty.el);
      else {
        restored = restorer.render(model.items, transcript);
        const last = model.items[model.items.length - 1];
        transcript.setLastDay(model.items.findLast?.((i) => i.at)?.at || last.at);
        if (resuming) transcript.content.append(createEvent(t('chat.resumedFrom', { date: formatDate(s.updated_at || last.at) })));
        transcript.scrollToBottom();
      }
      actions.refreshSessions({ silent: true });
    } catch (e) {
      if (disposed) return;
      if (e.status === 409 || e.code === 'tab_locked') { if (!store.get().status.locked) { actions.setStatus({ locked: true }); showLock(api, actions); } transcript.setEmpty(errorState({ title: t('err.tab_locked'), body: t('lock.body') })); }
      else transcript.setEmpty(errorState({ title: t('chat.loadError'), body: e.message, onRetry: () => router.refresh() }));
    }
    turn.refreshLock();
  }

  const onKey = (e) => {
    if (e.key !== 'Escape' || e.defaultPrevented || !turn.busy() || turn.approvalOpen()) return;
    if (document.querySelector('dialog[open], .popover')) return;
    e.preventDefault(); turn.interrupt();
  };
  const on = (type, fn) => { document.addEventListener(type, fn); return () => document.removeEventListener(type, fn); };
  const offs = [
    on('keydown', onKey),
    on('sensai:stop-request', () => turn.interrupt()),
    on('sensai:mock-prompt', (e) => composer.fill(e.detail.text)),
    on('sensai:persona-changed', (e) => {
      if (model.items.length) { const text = t('persona.changed', { name: e.detail.name }); model.items.push({ kind: 'event', text }); transcript.append(createEvent(text)); }
      empty.update();
    }),
    on('sensai:lang', () => { if (!turn.busy()) router.refresh(); }),
  ];
  const unsub = [store.subscribe(() => turn.refreshLock(), ['status']), store.subscribe(paintPrefs, ['prefs']), store.subscribe(() => empty.update(), ['personas', 'activePersona', 'config']), store.subscribe((s) => transcript.setStreaming(s.status.streaming), ['status'])];
  transcript.setStreaming(false);
  api.profile().then((p) => { name = p?.preferences?.name || ''; empty.update(); }).catch(() => {});
  load().then(() => { if (!disposed && !params.id) composer.focus(); });

  return () => {
    disposed = true;
    if (turn.busy()) turn.interrupt();
    printHead.unsub(); restored?.cancel(); reconnect.dispose(); offs.forEach((f) => f()); unsub.forEach((f) => f());
  };
}
