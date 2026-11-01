// The weekly run (T45) on the Campaign page: one button, one line per output as it finishes, Stop saves nothing.
import { h } from '../dom.js';
import { button } from '../components/button.js';
import { chip } from '../components/chip.js';
import { spinner } from '../components/meter.js';
import { toast } from '../components/toast.js';
import { announce } from '../a11y.js';
import { t } from '../i18n.js';

/** deps: { api, onDoc(doc) }. Returns { button, panel }. */
export function createWeeklyRun({ api, onDoc }) {
  const panel = h('div', { class: 'card stack', hidden: true, 'aria-live': 'polite' });
  let running = false;
  const run = button(t('weekly.run'), { variant: 'primary', icon: 'play', onClick: () => (running ? api.stopChat() : start()) });
  const setRunning = (on) => { running = on; run.querySelector('.btn__label').textContent = t(on ? 'weekly.stop' : 'weekly.run'); };
  const line = (e) => h('div', { class: 'row' }, chip(e.ok ? 'OK' : t('weekly.failed'), { tone: e.ok ? 'sage' : 'rose', icon: e.ok ? 'check' : null }),
    h('b', null, e.name), h('span', { class: 'muted', dir: 'auto' }, e.detail));

  async function start() {
    setRunning(true);
    const progress = h('p', { class: 'muted row' }, spinner(), t('weekly.working'));
    panel.hidden = false;
    panel.replaceChildren(h('h2', null, t('weekly.title')), progress);
    try {
      await api.weeklyRun({ onEvent: (e) => {
        if (e.type === 'start') progress.lastChild.textContent = t('weekly.reading', { folder: e.folder, model: e.model });
        else if (e.type === 'step') { panel.insertBefore(line(e), progress); announce(`${e.name}: ${e.ok ? 'OK' : t('weekly.failed')}`); }
        else if (e.type === 'done') {
          const text = e.status === 'stopped' ? t('weekly.stopped') : e.saved ? t('weekly.saved', { file: e.saved }) : t('weekly.nothing');
          progress.replaceWith(h('p', { class: 'muted' }, e.header ? `${e.header}. ` : '', text));
          if (e.doc) onDoc(e.doc);
          toast(text); announce(text);
        }
      } });
    } catch (e) { progress.replaceWith(h('p', { class: 'field__error', role: 'alert' }, e.message)); }
    finally { setRunning(false); }
  }

  return { button: run, panel };
}
