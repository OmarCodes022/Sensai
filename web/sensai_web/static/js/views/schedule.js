// Schedule (X5): the recurring tasks from the tasks file, when they run next, their last result and the drafts.
import { h } from '../dom.js';
import { chip } from '../components/chip.js';
import { button } from '../components/button.js';
import { emptyState } from '../components/state.js';
import { openModal } from '../components/modal.js';
import { toast } from '../components/toast.js';
import { viewShell, section } from '../components/view.js';
import { renderInto } from '../markdown.js';
import { formatDuration } from '../format.js';
import { t } from '../i18n.js';

const REFRESH_MS = 15000;

export function mount(root, { api }) {
  const intro = h('p', { class: 'muted' });
  const tasks = h('div', { class: 'stack' });
  const drafts = h('div', { class: 'stack' });
  root.append(viewShell('schedule', intro, section(t('schedule.tasks'), tasks), section(t('schedule.drafts'), drafts)));

  async function open(name) {
    try {
      const d = await api.draft(name);
      const body = h('div', { class: 'md docview__md', dir: 'auto' });
      renderInto(body, d.text, {});
      openModal({ title: name, body, wide: true, actions: [{ label: t('common.close'), variant: 'primary' }] });
    } catch (e) { toast(e.message, { tone: 'rose' }); }
  }

  function taskCard(x) {
    const last = x.last ? (x.last.ok ? chip(t('schedule.ok', { at: x.last.at.replace('T', ' ') }), { tone: 'sage', icon: 'check' })
      : chip(t('schedule.failed', { at: x.last.at.replace('T', ' ') }), { tone: 'rose', icon: 'x' })) : chip(t('schedule.notYet'), { outline: true });
    const run = button(t('schedule.runNow'), { icon: 'play', size: 'sm', onClick: async () => {
      run.disabled = true;
      try { const r = await api.runTask(x.name); toast(r.ok ? t('schedule.saved', { file: r.draft }) : r.error, { tone: r.ok ? undefined : 'rose' }); refresh(); }
      catch (e) { toast(e.message, { tone: 'rose' }); } finally { run.disabled = false; }
    } });
    return h('article', { class: 'card stack', 'aria-label': x.name },
      h('div', { class: 'row' }, h('b', { class: 'mono' }, x.name), x.persona ? chip(x.persona, { tone: 'accent' }) : null, h('span', { class: 'grow' }), last),
      h('p', { dir: 'auto' }, x.prompt),
      h('p', { class: 'muted' }, t('schedule.every', { every: formatDuration(x.every_minutes * 60000), next: formatDuration(x.next_in_seconds * 1000) })),
      x.last && !x.last.ok ? h('p', { class: 'field__error' }, x.last.error) : null, h('div', null, run));
  }

  async function refresh() {
    let s;
    try { s = await api.schedule(); } catch (e) { tasks.replaceChildren(h('p', { class: 'field__error' }, e.message)); return; }
    if (!s.on) {
      intro.textContent = '';
      tasks.replaceChildren(emptyState({ icon: 'clock', title: t('schedule.off'), body: t('schedule.offBody'), h: 'h3' }));
      drafts.replaceChildren();
      return;
    }
    intro.textContent = t('schedule.intro', { file: s.file, model: s.model });
    tasks.replaceChildren(...s.tasks.map(taskCard));
    drafts.replaceChildren(...(s.drafts.length ? [h('ul', { class: 'stack' }, s.drafts.map((d) => h('li', { class: 'row' },
      h('button', { type: 'button', class: 'link-btn mono', onclick: () => open(d.name) }, d.name), h('span', { class: 'muted' }, d.at.replace('T', ' ')))))]
      : [h('p', { class: 'muted' }, t('schedule.noDrafts'))]));
  }

  refresh();
  const timer = setInterval(refresh, REFRESH_MS);
  return () => clearInterval(timer);
}
