// Campaign preview (spec 9.1, mock data): header, four section tabs, command box, weekly run.
import { h } from '../../dom.js';
import { chip } from '../../components/chip.js';
import { button } from '../../components/button.js';
import { tabs } from '../../components/tabs.js';
import { confirmDialog } from '../../components/modal.js';
import { WEEK, SECTIONS } from '../../mock/planned-campaign.js';
import { postsPanel, dmPanel } from './campaign-posts.js';
import { reportPanel } from './campaign-report.js';
import { calendarPanel, printDoc } from './campaign-calendar.js';
import { commandBox, weeklyRun } from './campaign-edit.js';
import { t } from '../../i18n.js';

const PANELS = { posts: postsPanel, dm: dmPanel, report: reportPanel, calendar: calendarPanel };

export function mountPreview(root) {
  root.classList.add('has-print', 'campaign');
  const status = Object.fromEntries(SECTIONS);
  const stamp = {};
  const noop = (label, extra = {}) => button(label, { 'aria-disabled': 'true', 'data-tip': t('preview.inert'), onClick: (e) => e.preventDefault(), ...extra });
  const head = h('div', { class: 'row campaign__head' }, h('strong', { class: 'num' }, WEEK.id), h('span', { class: 'muted' }, `${WEEK.range} · ${WEEK.tz}`), h('span', { class: 'grow' }),
    button(t('preview.prev'), { icon: 'chevron-left', disabled: true }), button(t('preview.next'), { icon: 'chevron-right', disabled: true }),
    noop(t('campaign.prepare'), { variant: 'primary' }), noop(t('campaign.export')), noop(t('campaign.share')), button(t('campaign.print'), { icon: 'file', onClick: () => window.print() }));
  const lockNote = h('p', { class: 'muted' });
  const approve = button(t('campaign.approve'), { onClick: async () => {
    const id = tabEl.querySelector('[role=tab][aria-selected=true]').dataset.id;
    if (status[id] === 'approved') return;
    if (await confirmDialog({ title: t('campaign.approveTitle'), message: t('campaign.approveBody'), confirmLabel: t('campaign.approve') })) { status[id] = 'approved'; stamp[id] = new Date().toISOString().slice(0, 16).replace('T', ' '); tabEl.select(id); relabel(); }
  } });
  const label = (id) => h('span', { class: 'row' }, t(`campaign.tab.${id}`), chip(t(`campaign.status.${status[id]}`), { tone: status[id] === 'approved' ? 'sage' : 'amber', icon: status[id] === 'approved' ? 'lock' : null }));
  const items = SECTIONS.map(([id]) => ({ id, label: label(id), render: () => {
    approve.hidden = status[id] === 'approved';
    lockNote.textContent = status[id] === 'approved' ? t('campaign.locked', { at: stamp[id] || 'mock' }) : '';
    return h('div', { class: `stack ${status[id] === 'approved' ? 'is-locked' : ''}` }, PANELS[id]());
  } }));
  const tabEl = tabs({ label: t('campaign.sections'), items, selected: 'posts' });
  const relabel = () => SECTIONS.forEach(([id]) => { tabEl.querySelector(`[data-id="${id}"]`)?.replaceChildren(label(id)); });
  root.replaceChildren(h('div', { class: 'stack' }, h('p', { class: 'muted' }, t('preview.notice')), head, tabEl, h('div', { class: 'row' }, approve, lockNote),
    commandBox(() => status.posts === 'approved'), weeklyRun()), printDoc());
}
