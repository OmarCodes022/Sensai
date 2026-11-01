// Prompt versions (A4) on the Settings page: the dated versions, "use this version" (rollback), and a side-by-side comparison.
import { h } from '../dom.js';
import { chip } from '../components/chip.js';
import { button } from '../components/button.js';
import { field, select } from '../components/form.js';
import { toast } from '../components/toast.js';
import { formatDuration } from '../format.js';
import { announce } from '../a11y.js';
import { t } from '../i18n.js';

export function createPromptVersions({ api }) {
  const el = h('div', { class: 'stack' });
  const results = h('div', { class: 'stack', 'aria-live': 'polite' });

  function paint(d) {
    const rows = d.items.map((v) => h('div', { class: 'row card' }, h('code', { class: 'mono' }, v.name), h('span', { class: 'muted' }, t('prompts.lines', { n: v.lines, sha: v.sha256 })),
      h('span', { class: 'grow' }), d.active === v.name ? chip(t('prompts.inUse'), { tone: 'sage', icon: 'check' })
        : button(t('prompts.use'), { size: 'sm', onClick: () => use(v.name) })));
    const a = select(d.items.map((v) => [v.name, v.name]), { 'aria-label': 'A' });
    const b = select(d.items.map((v) => [v.name, v.name]), { 'aria-label': 'B' });
    if (d.items.length > 1) b.value = d.items[d.items.length - 1].name;
    if (d.items.length > 1) a.value = d.items[d.items.length - 2].name;
    const go = button(t('prompts.compare'), { variant: 'primary', icon: 'play', onClick: () => compare(a.value, b.value, go) });
    const running = d.active ? h('div', { class: 'row' }, chip(t('prompts.running', { name: d.active }), { tone: 'plum' }), button(t('prompts.original'), { size: 'sm', onClick: () => use(null) })) : '';
    el.replaceChildren(h('p', { class: 'muted' }, t('prompts.help'), ' ', h('code', null, d.folder)), running,
      ...rows, h('h3', null, t('prompts.compareTitle')), h('div', { class: 'row' }, field('A', a), field('B', b), go), results);
  }

  async function use(name) {
    try { paint(await api.usePrompt(name)); const m = name ? t('prompts.used', { name }) : t('prompts.backToOriginal'); toast(m); announce(m); }
    catch (e) { toast(e.message, { tone: 'rose' }); }
  }

  async function compare(a, b, go) {
    go.disabled = true;
    const table = h('div', { class: 'stack' });
    results.replaceChildren(h('p', { class: 'muted' }, t('prompts.comparing', { a, b })), table);
    const rows = new Map();
    try {
      await api.comparePrompts(a, b, { onEvent: (e) => {
        if (e.type === 'answer') {
          if (!rows.has(e.n)) { const r = h('div', { class: 'cards-3' }); rows.set(e.n, r); table.append(h('h4', null, `${e.n}. ${e.question}`), r); }
          rows.get(e.n).append(h('div', { class: 'card stack' }, h('strong', null, e.label),
            h('p', { class: 'muted' }, `${formatDuration(e.latency_ms)} · ${e.prompt_tokens ?? 'n/a'} in / ${e.output_tokens ?? 'n/a'} out`),
            e.error ? h('p', { class: 'field__error' }, e.error) : h('p', { dir: 'auto', class: 'code--wrap' }, e.text)));
        } else if (e.type === 'done') {
          results.firstChild.replaceWith(h('p', { class: 'muted' }, e.report ? t('prompts.report', { file: e.report }) : t('prompts.stopped')));
        }
      } });
    } catch (e) { results.replaceChildren(h('p', { class: 'field__error', role: 'alert' }, e.message)); }
    finally { go.disabled = false; }
  }

  api.promptVersions().then(paint).catch((e) => el.replaceChildren(h('p', { class: 'field__error' }, e.message)));
  return el;
}
