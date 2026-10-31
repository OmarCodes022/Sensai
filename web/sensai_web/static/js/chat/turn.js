// One chat turn: sends, folds stream events into the transcript, owns the timer, approvals, interruption and failures.
import { h } from '../dom.js';
import { createUser, createEvent } from './messages.js';
import { createAssistant } from './assistant.js';
import { createToolCard } from './tool-card.js';
import { createApproval } from './approval.js';
import { createErrorCard } from './error-card.js';
import { assistantOptions } from './shared.js';
import { showLock } from '../components/lock.js';
import { chip } from '../components/chip.js';
import { toast } from '../components/toast.js';
import { announce } from '../a11y.js';
import { stripInvisible } from '../safetext.js';
import { t } from '../i18n.js';

const LOCK_CODES = ['tab_locked'];

/** deps: { ctx, transcript, composer, model, reconnect, onReuse(text) } */
export function createTurn({ ctx, transcript, composer, model, reconnect, onReuse }) {
  const { store, api, actions, router } = ctx;
  let st = null;
  const limits = () => store.get().config?.limits || {};

  const lockReason = () => (store.get().status.locked ? 'locked' : store.get().status.backend === 'offline' && !store.get().status.mock ? 'offline' : st?.busy && [...st.approvals.values()].some((a) => a.isOpen()) ? 'approval' : null);
  const refreshLock = () => composer.setLock(lockReason());
  const openStatus = () => document.querySelector('.topbar .status-cluster button:first-child, .topbar .status-btn')?.click();

  function showLockOverlay() {
    if (store.get().status.locked) return;
    actions.setStatus({ locked: true }); showLock(api, actions);
  }
  function addNode(node, at) { transcript.append(node, at); }

  function ensureBlock(personaId) {
    if (st.block) return st.block;
    const o = assistantOptions(ctx, personaId || store.get().activePersona);
    st.block = createAssistant(o);
    const item = { kind: 'assistant', persona: o.persona.name, tools: [], get text() { return st.block?.text() ?? ''; }, interrupted: false };
    model.items.push(item); st.item = item;
    addNode(st.block.el, new Date().toISOString());
    return st.block;
  }

  function tick() {
    if (!st.paused) st.elapsed += 0.25;
    const s = Math.floor(st.elapsed);
    composer.setRing((st.elapsed / st.budget) * 100);
    st.block?.setElapsed(s);
    composer.setElapsed(st.block?.hasContent() ? t('chat.replying', { s }) : t('chat.thinkingS', { s }));
  }

  function resolveApproval(id, approved) {
    const ap = st.approvals.get(id);
    if (!ap || st.resolved.has(id)) return;
    st.resolved.add(id);
    ap.settle(approved);
    const card = st.cards.get(ap.callId);
    card?.setStatus(approved ? 'running' : 'refused');
    st.paused = false; refreshLock();
    announce(approved ? t('approval.running') : t('approval.refused'));
  }

  function handle(ev) {
    switch (ev.type) {
      case 'turn_start': st.budget = ev.budget_seconds || limits().turn_seconds || 120; ensureBlock(ev.persona); break;
      case 'text': ensureBlock().appendText(ev.delta); break;
      case 'tool_call': {
        const card = createToolCard(ev, { max: limits().tool_rounds ?? 5, showJson: store.get().prefs.showToolJson });
        st.calls.set(ev.id, ev); st.cards.set(ev.id, card); st.item.tools.push({ name: ev.name, arguments: ev.arguments });
        ensureBlock().addTool(card.el); announce(t('tool.started', { name: ev.name })); break;
      }
      case 'approval_request': {
        const ap = createApproval(ev, { getCall: (id) => st.calls.get(id), onDecide: async (ok) => { await api.approve(ev.id, ok); setTimeout(() => resolveApproval(ev.id, ok), 0); } });
        ap.callId = ev.call_id; st.approvals.set(ev.id, ap); st.cards.get(ev.call_id)?.setStatus('waiting');
        ensureBlock().addApproval(ap.el); st.paused = true; refreshLock();
        announce(t('approval.title', { action: ev.action }));
        requestAnimationFrame(() => { ap.el.scrollIntoView({ block: 'nearest' }); ap.focus(); }); break;
      }
      case 'approval_result': resolveApproval(ev.id, ev.approved); break;
      case 'tool_result': st.cards.get(ev.id)?.setResult(ev); st.approvals.forEach((a) => { if (a.callId === ev.id) a.finished(ev.ok); }); announce(t('tool.finished', { name: ev.name })); break;
      case 'usage': st.usage = { prompt_tokens: ev.prompt_tokens, output_tokens: ev.output_tokens, latency_ms: ev.latency_ms, server_duration_ms: ev.server_duration_ms }; break;
      case 'title': store.set({ session: { ...store.get().session, title: ev.title } }); document.title = `${stripInvisible(ev.title)} - Sensai`; break;
      case 'saved': store.set({ session: { ...store.get().session, saved: true } }); announce(t('session.saved')); break;
      case 'warning': warn(ev); break;
      case 'redacted': st.user.addNote(chip(t('guard.redacted', { classes: (ev.parts || []).map((p) => p.class).join(', ') }), { tone: 'plum', icon: 'eye-off' })); break;
      case 'blocked': st.blocked = true; addError({ code: 'guardrail_refused', message: ev.message, reason: ev.reason }); break;
      case 'sources': st.block?.setSources(ev.items); break;
      case 'step': ensureBlock().addStep(ev.step, ev.text); break;
      case 'done': st.status = ev.status; break;
      case 'error': st.failed = true; fail(ev); break;
      default: break;
    }
  }

  function warn(ev) {
    if (ev.code === 'storage') addError({ code: 'storage', message: ev.message });
    else if (ev.code === 'tool_round_limit') ensureBlock().addNote(h('div', { class: 'evt' }, h('span', null, t('tools.roundLimit'))));
    else addNode(createEvent(ev.message || ev.code));
  }

  function addError(err, { noRetry = false } = {}) {
    const me = st;
    const card = createErrorCard(err, { retry: noRetry ? null : () => retry(me), reconnect: () => reconnect.now(), goto: (p) => router.go(p), openStatus,
      takeover: () => api.takeover().then(() => { actions.setStatus({ locked: false }); card.el.remove(); refreshLock(); }).catch((e) => toast(e.message, { tone: 'rose' })) });
    me.errEls.push(card.el);
    addNode(card.el, new Date().toISOString());
    return card;
  }

  function fail(err) {
    const b = st.block;
    if (b && !b.hasContent()) { b.discard(); model.items = model.items.filter((i) => i !== st.item); } else if (b) { b.markInterrupted(); st.item.interrupted = true; st.dropped.push(b); }
    if (!st.blocked) st.user.markNotSent(true);
    st.cards.forEach((c) => c.cancel());
    const locked = LOCK_CODES.includes(err.code) || err.status === 409;
    addError(err, { noRetry: locked });
    if (locked) showLockOverlay();
    if (err.code === 'network') reconnect.start();
  }

  /** Removes the failed turn from view and sends its text again. */
  function retry(me) {
    if (st?.busy) return;
    [me.userEl, ...me.errEls].forEach((n) => n.remove());
    model.items = model.items.filter((i) => i.kind !== 'user' || i.n);
    send(me.text);
  }

  function complete() {
    if (st.blocked) { st.block?.discard(); model.items = model.items.filter((i) => i !== st.item); st.user.markNotSent(false); return; }
    const n = model.items.filter((i) => i.kind === 'user' && i.n).length + 1;
    st.user.setNumber(n);
    const words = (st.block || ensureBlock()).finish(st.usage ?? null);
    st.item.usage = st.usage;
    model.dropped.forEach((b) => b.collapse()); model.dropped = [];
    announce(t('chat.replyComplete', { n: words }));
  }

  function interruptedUi(timedOut) {
    st.block?.markInterrupted(); if (st.item) st.item.interrupted = true; if (st.block) st.dropped.push(st.block);
    st.user.markNotSent(timedOut); st.cards.forEach((c) => c.cancel());
    st.approvals.forEach((a) => a.dispose());
    addNode(createEvent(timedOut ? t('chat.timedOutDivider') : t('chat.interruptedDivider')));
    if (timedOut) addError({ code: 'turn_timeout', message: '', seconds: st.budget });
    else { toast(t('chat.interruptedToast')); announce(t('chat.interruptedToast')); }
  }

  async function send(text) {
    if (st?.busy) return;
    const at = new Date().toISOString();
    const me = {};
    const user = createUser({ kind: 'user', text, at }, { onReuse, onRetry: () => retry(me) });
    const item = user.item;
    model.items.push(item);
    st = me;
    Object.assign(me, { busy: true, text, user, userEl: user.el, errEls: [], ac: new AbortController(), elapsed: 0, paused: false, budget: limits().turn_seconds || 120, calls: new Map(), cards: new Map(), approvals: new Map(), resolved: new Set(), dropped: [], block: null, item: null, status: null, failed: false, interrupted: false, blocked: false, usage: undefined });
    addNode(user.el, at);
    actions.setStatus({ streaming: true }); composer.setStreaming(true); composer.setElapsed(t('chat.thinkingS', { s: 0 }));
    const timer = setInterval(tick, 250);
    st.dropped = model.dropped;
    try {
      const asked = /^\/think\s+([\s\S]+)$/i.exec(text);  // /think <request> runs the step-by-step loop
      await api.chat(asked ? asked[1] : text, { signal: st.ac.signal, onEvent: handle, think: !!asked });
      if (st.failed) { /* error card already shown */ }
      else if (st.status === 'completed') complete();
      else if (st.status === 'interrupted') interruptedUi(false);
      else if (st.status === 'timed_out') interruptedUi(true);
      else fail({ code: 'network', message: 'stream ended without done' });
    } catch (e) {
      if (e.name === 'AbortError' && st.interrupted) interruptedUi(false);
      else if (!(st.failed && e.code === 'network')) fail({ code: e.code || 'llm_error', message: e.message, hint: e.hint, status: e.status });
    } finally {
      clearInterval(timer);
      st.busy = false; actions.setStatus({ streaming: false });
      composer.setStreaming(false); refreshLock();
      if (!document.querySelector('dialog[open]')) composer.focus();
      if (st.status === 'completed' && !st.failed) {
        api.session().then((s) => store.set({ session: s })).catch(() => {});
        actions.refreshSessions({ silent: true });
      }
    }
  }

  return {
    send, refreshLock,
    busy: () => !!st?.busy,
    approvalOpen: () => lockReason() === 'approval',
    interrupt() {
      if (!st?.busy || st.interrupted) return;
      st.interrupted = true; st.ac.abort(); api.stopChat().catch(() => {});
    },
  };
}
