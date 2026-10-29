// Sessions view (spec 7): sortable table, persona filter, detail panel; cards under 768 px.
import { h } from '../dom.js';
import { icon } from '../icons.js';
import { chip } from '../components/chip.js';
import { select, field } from '../components/form.js';
import { emptyState, errorState, skeletonRows } from '../components/state.js';
import { viewShell } from '../components/view.js';
import { createDetail } from '../sessions/detail.js';
import { formatNumber, formatDate, formatUtc } from '../format.js';
import { stripInvisible } from '../safetext.js';
import { hrefFor } from '../router.js';
import { t } from '../i18n.js';

const COLS = ['title', 'id', 'persona', 'messages', 'created_at', 'updated_at'];
const LABEL = { title: 'title', id: 'id', persona: 'persona', messages: 'messages', created_at: 'created', updated_at: 'updated' };

export function mount(root, { store, actions, router, api }) {
  let sort = { key: 'updated_at', dir: 'desc' }, filter = '', selected = null;
  const personaName = (id) => store.get().personas.find((p) => p.id === id)?.name || id;
  const detail = createDetail({ api, personaName, onOpen: open });

  async function open(id) {
    if (store.get().status.streaming && !(await actions.confirmStop())) return;
    router.go(hrefFor('chat', id));
  }

  const filterSel = select([['', t('sessions.allPersonas')]], { 'aria-label': t('sessions.filterPersona') });
  filterSel.addEventListener('change', () => { filter = filterSel.value; paint(); });
  const body = h('div', { class: 'sess-table' });
  const live = h('p', { class: 'sr-only', role: 'status' });
  root.append(viewShell('sessions', h('div', { class: 'row' }, field(t('sessions.filterPersona'), filterSel)), h('div', { class: 'sess-layout' }, body, detail.el), live));

  const val = (s, k) => (k === 'persona' ? personaName(s.persona) : k === 'messages' ? (s.messages ?? -1) : s[k] ?? '');
  const cmp = (a, b) => {
    const x = val(a, sort.key), y = val(b, sort.key);
    const r = typeof x === 'number' ? x - y : String(x).localeCompare(String(y));
    return sort.dir === 'asc' ? r : -r;
  };

  function head(k) {
    const on = sort.key === k;
    const dflt = k === 'messages' || k.endsWith('_at') ? 'desc' : 'asc';
    const b = h('button', { type: 'button', onclick: () => {
      sort = { key: k, dir: on ? (sort.dir === 'asc' ? 'desc' : 'asc') : dflt };
      live.textContent = t('sessions.sortedBy', { col: t(`sessions.col.${LABEL[k]}`), dir: t(`sessions.dir.${sort.dir}`) });
      paint(); body.querySelector(`th[data-k="${k}"] button`)?.focus();
    } },
      t(`sessions.col.${LABEL[k]}`), on ? icon(sort.dir === 'asc' ? 'chevron-up' : 'chevron-down', { size: 14 }) : null);
    return h('th', { scope: 'col', 'data-k': k, 'aria-sort': on ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none' }, b);
  }

  function row(s) {
    const untitled = !s.title || s.title === '(sans titre)';
    const branch = /\(branch\)$/.test(s.title || '');
    const pick = h('button', { type: 'button', class: `link-btn sess-pick ${untitled ? 'is-untitled' : ''}`, 'aria-pressed': String(selected === s.id), onclick: () => { selected = s.id; detail.show(s); paintSel(); } },
      branch ? icon('branch', { size: 14 }) : null, untitled ? t('sessions.untitled') : stripInvisible(s.title));
    const time = (iso) => h('time', { datetime: iso, 'data-tip': formatUtc(iso) }, formatDate(iso));
    const cells = [pick, h('span', { class: 'mono' }, s.id), s.persona ? chip(personaName(s.persona), { tone: 'accent' }) : t('common.na'), formatNumber(s.messages), time(s.created_at), time(s.updated_at)];
    return h('tr', { 'aria-selected': String(selected === s.id), dataset: { id: s.id } }, cells.map((c, i) => h('td', { class: i === 3 ? 'num' : '', 'data-label': t(`sessions.col.${LABEL[COLS[i]]}`) }, c)));
  }
  const paintSel = () => body.querySelectorAll('tbody tr').forEach((tr) => {
    const on = tr.dataset.id === selected;
    tr.setAttribute('aria-selected', String(on)); tr.querySelector('.sess-pick').setAttribute('aria-pressed', String(on));
  });

  function paint() {
    const { items, state } = store.get().sessions;
    const ids = [...new Set(items.map((s) => s.persona).filter(Boolean))];
    if (filterSel.options.length - 1 !== ids.length) { filterSel.replaceChildren(h('option', { value: '' }, t('sessions.allPersonas')), ...ids.map((id) => h('option', { value: id }, personaName(id)))); filterSel.value = filter; }
    if (state === 'loading' && !items.length) return body.replaceChildren(skeletonRows(6));
    if (state === 'error') return body.replaceChildren(errorState({ title: t('sessions.loadError'), onRetry: () => actions.refreshSessions() }));
    const shown = items.filter((s) => !filter || s.persona === filter).sort(cmp);
    if (!shown.length) return body.replaceChildren(emptyState({ icon: 'history', title: items.length ? t('sessions.noMatch') : t('sessions.empty') }));
    body.replaceChildren(h('div', { class: 'table-wrap' }, h('table', { class: 'table table--cards' }, h('caption', { class: 'sr-only' }, t('sessions.tableCaption')),
      h('thead', null, h('tr', null, COLS.map(head))), h('tbody', null, shown.map(row)))));
  }
  const unsub = store.subscribe(paint, ['sessions', 'personas']);
  paint();
  actions.refreshSessions();
  return unsub;
}
