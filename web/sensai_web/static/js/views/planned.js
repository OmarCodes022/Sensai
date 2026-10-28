// Planned state (spec 9.0): shown for any route whose capability flag is false.
import { h } from '../dom.js';
import { icon } from '../icons.js';
import { chip } from '../components/chip.js';
import { toggle } from '../components/form.js';
import { t } from '../i18n.js';

const OWNERS = { T40: 'Diana', T45: 'Omar', T46: 'Maryam', T50: 'Maryam', T53: 'Maryam', T32: 'Maryam', T07: 'Omar', T35: 'Maryam', T36: 'Maryam', T43: 'Maryam', T33: 'Diana', T38: 'Diana', T10: 'Diana', T47: 'Diana', T51: 'Omar' };

export function mount(root, { router, store }) {
  const { route } = router.current;
  const name = route.name;
  const title = t(`nav.${name}`);
  document.title = `${title} - Sensai`;
  const owners = [...new Set(route.tasks.map((x) => OWNERS[x]))].join(', ');
  const previewBox = h('div', { class: 'card ribbon preview-box', hidden: true });
  const on = toggle(t('planned.mockToggle'), { onChange: async (v) => {
    previewBox.hidden = !v;
    previewBox.replaceChildren();
    if (!v) return;
    try { const m = await import(`./preview/${name}.js`); await m.mountPreview(previewBox, { store }); }
    catch { previewBox.append(h('p', { class: 'muted' }, t('planned.noPreview'))); }
  } });
  root.append(h('div', { class: 'view' }, h('div', { class: 'planned' },
    h('div', { class: 'row' }, icon(route.icon, { size: 28 }), h('h1', null, title), chip(t('common.planned'), { tone: 'amber' })),
    h('div', { class: 'row' }, ...route.tasks.map((x) => chip(x, { mono: true, outline: true })), h('span', { class: 'muted' }, t('planned.owners', { owners }))),
    h('p', null, t(`planned.${name}.desc`)),
    h('div', null, h('h2', null, t('planned.youWillBeAbleTo')), h('ul', null, [1, 2, 3].map((i) => h('li', null, t(`planned.${name}.b${i}`))))),
    h('div', null, h('h2', null, t('planned.acceptance')), h('ul', { class: 'checks' }, [1, 2, 3].map((i) => h('li', null, t(`planned.${name}.c${i}`))))),
    h('div', { class: 'card card--flat stack' }, h('p', { class: 'muted' }, t('planned.mockNote')), on),
    previewBox)));
}
