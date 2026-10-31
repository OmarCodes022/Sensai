// One assistant message: header, tool group, Markdown body, tags and footer. Streams, finishes, or is interrupted.
import { h } from '../dom.js';
import { icon } from '../icons.js';
import { renderInto } from '../markdown.js';
import { chip } from '../components/chip.js';
import { copyButton } from '../components/copy-button.js';
import { usageChips } from './usage.js';
import { wordCount } from '../format.js';
import { t } from '../i18n.js';

function toolGroup() {
  const el = h('details', { class: 'toolgroup', open: true, dataset: { n: '0' } }, h('summary', null));
  const sum = el.firstChild;
  return { el, count: () => Number(el.dataset.n), add(node) {
    el.append(node); el.dataset.n = String(Number(el.dataset.n) + 1); sum.textContent = t('tools.group', { n: el.dataset.n });
  } };
}

/** opts: { persona:{name,id}, tone, draft:boolean, onDetails(usage), onGrow() } */
export function createAssistant(opts) {
  let text = '', sources = null, timer = null, last = 0, streaming = true, usage = null, state = 'streaming';
  const name = opts.persona?.name || '';
  const think = h('span', { class: 'msg__think' }, h('span', { class: 'dots', 'aria-hidden': 'true' }, h('i'), h('i'), h('i')), h('span', null, t('chat.thinking')), h('span', { class: 'num' }));
  const group = toolGroup();
  const body = h('div', { class: 'msg__body md', dir: 'auto' });
  const tags = h('div', { class: 'msg__tags' });
  const foot = h('footer', { class: 'msg__foot', hidden: true });
  const cited = h('div', { class: 'msg__sources row', hidden: true });
  const web = h('div', { class: 'msg__sources stack', hidden: true });  // Web search results the reply could cite (T3).
  const steps = h('ol', { class: 'steps', hidden: true });
  body.addEventListener('click', (e) => { const b = e.target.closest('.md-cite'); if (b) opts.onCite?.(Number(b.dataset.cite), sources); });
  const el = h('article', { class: 'msg msg--assistant', 'aria-busy': 'true', 'aria-label': t('msg.assistantLabel', { name }), tabindex: '-1' },
    h('header', { class: 'msg__head' }, h('span', { class: 'avatar', dataset: { tone: opts.tone || 'accent' }, 'aria-hidden': 'true' }, (name[0] || '?').toUpperCase()), h('span', { class: 'msg__who' }, name), think),
    group.el, steps, body, cited, web, tags, foot);
  group.el.hidden = true;

  const caret = () => {
    el.querySelector('.caret')?.remove();
    if (!streaming || !text) return;
    let host = body.lastElementChild;
    if (host && /^(UL|OL)$/.test(host.tagName)) host = host.lastElementChild;
    if (!host || !/^(P|LI|H\d)$/.test(host.tagName)) host = body;
    host.append(h('span', { class: 'caret', 'aria-hidden': 'true' }));
  };
  const paint = () => {
    timer = null; last = performance.now();
    renderInto(body, text, { streaming, sources });
    caret(); opts.onGrow?.();
  };
  const schedule = () => { if (!timer) timer = setTimeout(paint, Math.max(0, (text.length > 4000 ? 120 : 40) - (performance.now() - last))); };
  const settled = () => { think.hidden = true; };

  const api = {
    el, state: () => state, text: () => text, usage: () => usage, hasContent: () => !!text || group.count() > 0,
    appendText(d) { settled(); text += d; schedule(); },
    setText(s) { text = s; paint(); },
    setElapsed(s) { think.lastChild.textContent = ` ${s} s`; },
    addNote(node) { settled(); group.el.hidden = false; group.el.append(node); },
    addTool(node) { settled(); group.el.hidden = false; group.add(node); },
    /** An approval blocks the turn: reopen the group if it was collapsed, or the card stays hidden. */
    addApproval(node) { settled(); group.el.hidden = false; group.el.open = true; group.add(node); },
    addStep(step, line) { settled(); steps.hidden = false; steps.append(h('li', null, h('span', { class: 'chip chip--outline' }, step), ' ', line)); },
    setWebSources(items) {
      web.hidden = !items?.length;
      web.replaceChildren(...(items?.length ? [h('span', { class: 'muted' }, t('msg.webSources')), h('ol', { class: 'web-sources' }, items.map((s) => h('li', null,
        h('span', { class: 'num mono' }, `[${s.n}] `), /^https?:\/\//.test(s.url) ? h('a', { href: s.url, target: '_blank', rel: 'noopener noreferrer' }, s.title) : s.title,
        s.date ? h('span', { class: 'muted' }, ` · ${s.date}`) : null)))] : []));
    },
    setSources(items, meta = {}) {
      sources = items;
      cited.hidden = !items?.length;
      const kept = meta.candidates ? h('span', { class: 'muted' }, t(meta.reranked ? 'msg.keptOf' : 'msg.keptBasic', { k: meta.kept, n: meta.candidates })) : null;
      cited.replaceChildren(...(items?.length ? [h('span', { class: 'muted' }, t('msg.sources')), ...items.map((s) => chip(`${s.n ? `${s.n}. ` : ''}${s.source}${s.version ? ` ${s.version}` : ''}${s.relevance != null ? ` · ${s.relevance}/10` : ''}${s.outdated ? ` (${t('msg.outdated')})` : ''}`, { outline: true, tone: s.outdated ? 'amber' : undefined, mono: true })), kept] : []));
      if (!streaming) paint();
    },
    finish(u) {
      streaming = false; state = 'done'; usage = u || null; clearTimeout(timer); settled();
      el.removeAttribute('aria-busy'); paint();
      foot.hidden = false; foot.replaceChildren(
        h('span', { class: 'msg__actions row' }, copyButton(() => body.textContent, { label: t('msg.copyPlain') }), copyButton(() => text, { label: t('msg.copyMd') }),
          h('button', { type: 'button', class: 'btn btn--ghost btn--sm', onclick: () => opts.onDetails?.(usage) }, t('msg.details'))),
        h('span', { class: 'usage-chips row' }, usageChips(usage)));
      if (opts.draft && text) tags.append(h('span', { class: 'chip chip--amber draft-label' }, icon('info', { size: 12 }), t('draft.label')));
      return wordCount(text);
    },
    markInterrupted() {
      streaming = false; state = 'interrupted'; clearTimeout(timer); settled(); el.removeAttribute('aria-busy'); el.classList.add('msg--interrupted');
      paint(); tags.replaceChildren(h('span', { class: 'chip chip--amber' }, icon('alert-triangle', { size: 12 }), t('chat.interrupted')));
      el.querySelectorAll('.approval').forEach((a) => a.remove());
    },
    /** After the next successful turn an interrupted reply shrinks to one expandable line. */
    collapse() {
      if (state !== 'interrupted') return;
      state = 'collapsed';
      el.classList.remove('msg--interrupted');
      el.replaceChildren(h('details', { class: 'msg__collapsed' }, h('summary', null, t('msg.interruptedHidden')), ...[...el.childNodes]));
    },
    discard: () => { clearTimeout(timer); el.remove(); },
  };
  return api;
}
