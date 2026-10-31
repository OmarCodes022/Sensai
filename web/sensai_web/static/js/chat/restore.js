// Builds transcript nodes from display-ready session items; the last 60 render now, older ones on idle.
import { createUser, createEvent, createDate, dayKey } from './messages.js';
import { createAssistant } from './assistant.js';
import { toolCardFromItem } from './tool-card.js';
import { assistantOptions } from './shared.js';
import { h } from '../dom.js';

const RECENT = 60;
const idle = (fn) => (window.requestIdleCallback ? requestIdleCallback(fn, { timeout: 400 }) : setTimeout(fn, 30));

/** deps: { ctx, onReuse(text), onEdit(item, text) }. Returns node builders bound to the current context. */
export function createRestorer({ ctx, onReuse, onEdit }) {
  const toolOpts = () => ({ max: ctx.store.get().config?.limits?.tool_rounds ?? 5, showJson: ctx.store.get().prefs.showToolJson });

  function node(it) {
    if (it.kind === 'user') return createUser(it, { onReuse, onEdit }).el;
    if (it.kind === 'event') return createEvent(it.text);
    if (it.kind === 'tool') return h('div', { class: 'toolgroup' }, toolCardFromItem(it, toolOpts()).el);
    const block = createAssistant(assistantOptions(ctx, it.persona));
    (it.tools || []).forEach((tool) => block.addTool(toolCardFromItem(tool, toolOpts()).el));
    if (it.sources) block.setSources(it.sources);
    block.setText(it.text || '');
    block.finish(it.usage ?? null);
    return block.el;
  }

  /** Items with a day separator flag, computed once over the whole list. */
  function entries(items) {
    let prev = null;
    return items.map((it) => {
      const day = dayKey(it.at) || prev;
      const sep = !!it.at && day !== prev;
      if (day) prev = day;
      return { it, sep };
    });
  }
  const nodesFor = (list) => list.flatMap((e) => [e.sep ? createDate(e.it.at) : null, node(e.it)]).filter(Boolean);

  /** Appends the recent tail to transcript, then prepends older chunks while idle. Returns cancel(). */
  function render(items, transcript) {
    const all = entries(items);
    const rest = all.slice(0, Math.max(0, all.length - RECENT));
    transcript.content.append(...nodesFor(all.slice(rest.length)));
    let cancelled = false;
    const step = () => {
      if (cancelled || !rest.length) return;
      transcript.prepend(nodesFor(rest.splice(-20)));
      if (rest.length) idle(step);
    };
    if (rest.length) idle(step);
    return { cancel: () => { cancelled = true; }, flush: () => { while (rest.length) transcript.prepend(nodesFor(rest.splice(-20))); } };
  }
  return { render, node };
}
