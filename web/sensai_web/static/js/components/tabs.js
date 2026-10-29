import { h, nextId } from '../dom.js';
import { rovingTabindex } from '../a11y.js';

/** tabs({label, items:[{id,label,render:()=>Node}], selected, onChange}). Automatic activation. */
export function tabs({ label, items, selected, onChange }) {
  const uid = nextId('tabs');
  const list = h('div', { class: 'tabs', role: 'tablist', 'aria-label': label });
  const panel = h('div', { class: 'tabpanel', role: 'tabpanel', tabindex: '0' });
  const root = h('div', { class: 'tabs-root' }, list, panel);
  const btns = items.map((it) => {
    const b = h('button', { type: 'button', class: 'tab', role: 'tab', id: `${uid}-${it.id}`, 'aria-controls': `${uid}-panel`, dataset: { id: it.id } }, it.label);
    list.append(b);
    return b;
  });
  panel.id = `${uid}-panel`;
  function select(id) {
    const it = items.find((x) => x.id === id) || items[0];
    btns.forEach((b) => b.setAttribute('aria-selected', String(b.dataset.id === it.id)));
    panel.setAttribute('aria-labelledby', `${uid}-${it.id}`);
    panel.replaceChildren(it.render());
    onChange?.(it.id);
  }
  list.addEventListener('click', (e) => { const b = e.target.closest('.tab'); if (b) select(b.dataset.id); });
  rovingTabindex(list, '.tab', { orientation: 'horizontal', onActivate: (b) => select(b.dataset.id) });
  select(selected || items[0].id);
  list.querySelectorAll('.tab').forEach((b) => b.setAttribute('tabindex', b.getAttribute('aria-selected') === 'true' ? '0' : '-1'));
  root.select = select;
  return root;
}
