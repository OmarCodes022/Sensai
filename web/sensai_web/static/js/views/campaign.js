// Campaign (M4, T5, A3): the week's living document, edited one schema-checked item at a time.
import { h } from '../dom.js';
import { chip } from '../components/chip.js';
import { button } from '../components/button.js';
import { select, field } from '../components/form.js';
import { confirmDialog } from '../components/modal.js';
import { emptyState } from '../components/state.js';
import { tabs } from '../components/tabs.js';
import { toast } from '../components/toast.js';
import { viewShell } from '../components/view.js';
import { formatNumber } from '../format.js';
import { announce } from '../a11y.js';
import { exportLine } from '../chat/export-command.js';
import { t } from '../i18n.js';
import { createWeeklyRun } from '../campaign/weekly-run.js';
import { createShare } from '../campaign/share.js';

const TABS = [['posts', 'posts'], ['replies', 'dm'], ['report', 'report'], ['calendar', 'calendar']];
const none = (key) => emptyState({ icon: 'calendar', title: t(key), h: 'h3' });

function posts(s) {
  if (!s.items.length) return none('campaign.noItems');
  return h('div', { class: 'cards-3' }, s.items.map((p) => h('article', { class: 'card stack', 'aria-label': p.id },
    h('div', { class: 'row' }, h('b', { class: 'mono' }, p.id), h('span', { class: 'grow' }), h('span', { class: 'muted' }, p.channel)),
    h('p', { class: 'post__text', dir: 'auto' }, p.caption),
    h('div', { class: 'row' }, p.claim_ids.length ? p.claim_ids.map((c) => chip(c, { tone: 'sage', icon: 'check' })) : chip(t('campaign.claimsNone'), { outline: true })),
    h('p', { class: 'muted' }, t('campaign.neverPublished')))));
}

function replies(s) {
  if (!s.items.length) return none('campaign.runOnly');
  return h('div', { class: 'cards-3' }, s.items.map((d) => h('article', { class: 'card stack', 'aria-label': d.case_key },
    h('div', { class: 'row' }, h('b', { class: 'mono' }, d.case_key), h('span', { class: 'grow' }), chip(t('campaign.unsent'), { tone: 'amber' })),
    h('p', { class: 'muted' }, t('campaign.question')), h('p', { dir: 'auto' }, d.question),
    h('p', { class: 'muted' }, t('campaign.suggestion')), h('p', { dir: 'auto' }, d.suggestion))));
}

function report(s) {
  const r = s.item;
  if (!r) return none('campaign.noReport');
  const rows = [[t('campaign.period'), `${r.period_start} to ${r.period_end}`], [t('campaign.tz'), r.timezone], [t('campaign.source'), h('code', null, r.source)],
    [t('campaign.reached'), r.accounts_reached == null ? t('common.na') : formatNumber(r.accounts_reached)],
    [t('campaign.engaged'), r.accounts_engaged == null ? t('common.na') : formatNumber(r.accounts_engaged)], [t('campaign.rate'), r.engagement_rate]];
  return h('div', { class: 'stack' }, h('div', { class: 'table-wrap' }, h('table', { class: 'table' }, h('tbody', null, rows.map(([k, v]) => h('tr', null, h('th', { scope: 'row' }, k), h('td', { class: 'num' }, v)))))),
    h('p', { class: 'muted' }, t('campaign.formula'), ' ', h('code', null, 'accounts_engaged / accounts_reached x 100')),
    r.interpretation ? h('blockquote', { class: 'interp card card--flat' }, h('strong', null, t('campaign.interp')), h('p', null, r.interpretation)) : null);
}

function calendar(s) {
  if (!s.items.length) return none('campaign.noItems');
  const sorted = [...s.items].sort((a, b) => `${a.date} ${a.time}`.localeCompare(`${b.date} ${b.time}`));
  return h('div', { class: 'stack' }, h('ul', { class: 'stack' }, sorted.map((e) => h('li', { class: 'card row' },
    h('b', { class: 'num' }, `${e.date} ${e.time}`), h('b', { class: 'mono' }, e.id), h('span', { class: 'mono' }, e.post_id),
    h('span', { class: 'muted' }, `${e.channel} · ${e.theme}`), chip(t('campaign.proposal'), { tone: 'amber' })))),
    h('p', { class: 'muted' }, t('campaign.notScheduled')));
}

const RENDER = { posts, replies, report, calendar };

export function mount(root, { api }) {
  let doc = null, selected = 'posts';
  const head = h('div', { class: 'row campaign__head' });
  const body = h('div', { class: 'stack' });
  const out = h('div', { 'aria-live': 'polite' });
  const which = select([['posts', t('campaign.tab.posts')], ['calendar', t('campaign.tab.calendar')]], { 'aria-label': t('campaign.section') });
  const request = h('input', { class: 'input', placeholder: t('campaign.requestPlaceholder'), autocomplete: 'off' });
  const ask = button(t('campaign.ask'), { variant: 'primary', icon: 'send' });
  const weekly = createWeeklyRun({ api, onDoc: (d) => { doc = d; paint(); } });
  const sharing = createShare({ api, out });
  root.classList.add('campaign');
  root.append(viewShell('campaign', head, weekly.panel, body, h('div', { class: 'card stack' }, h('h2', null, t('campaign.cmd')),
    h('div', { class: 'row' }, field(t('campaign.section'), which), field(t('campaign.requestLabel'), request)), h('div', null, ask),
    h('p', { class: 'muted' }, t('campaign.cmdHelpLive')), out), sharing.list));

  function paint() {
    if (!doc) return;
    head.replaceChildren(h('strong', { class: 'num' }, doc.week), h('span', { class: 'muted' }, `${doc.start} to ${doc.end} · ${doc.timezone}`),
      h('span', { class: 'grow' }), h('code', { class: 'muted' }, doc.file), weekly.button,
      button(t('campaign.export'), { icon: 'download', onClick: async () => {
        try { const r = await api.exportAll(); out.replaceChildren(exportLine(t('export.campaign'), r.campaign), exportLine(t('export.conversation'), r.conversation)); }
        catch (e) { out.replaceChildren(h('p', { class: 'field__error', role: 'alert' }, e.message)); }
      } }));
    const label = (id, key) => { const st = doc.sections[id].status; return h('span', { class: 'row' }, t(`campaign.tab.${key}`), chip(t(`campaign.status.${st}`), { tone: st === 'approved' ? 'sage' : 'amber', icon: st === 'approved' ? 'lock' : null })); };
    const items = TABS.map(([id, key]) => ({ id, label: label(id, key), render: () => {
      const s = doc.sections[id];
      const approve = s.status === 'approved' ? h('p', { class: 'muted' }, t('campaign.locked', { at: (s.approved_at || '').slice(0, 16).replace('T', ' ') }))
        : button(t('campaign.approve'), { onClick: () => approveSection(id) });
      return h('div', { class: 'stack' }, RENDER[id](s), h('div', { class: 'row' }, approve, sharing.button(id)));
    } }));
    body.replaceChildren(tabs({ label: t('campaign.sections'), items, selected, onChange: (id) => { selected = id; } }));
  }

  async function approveSection(id) {
    if (!(await confirmDialog({ title: t('campaign.approveTitle'), message: t('campaign.approveBody'), confirmLabel: t('campaign.approve') }))) return;
    try { doc = await api.campaignApprove(id); selected = id; paint(); } catch (e) { toast(e.message, { tone: 'rose' }); }
  }

  const done = (message) => { out.replaceChildren(h('p', { class: 'muted', role: 'status' }, message)); toast(message); announce(message); };

  function confirmCard(r) {
    const decide = async (ok) => {
      try { const res = await api.campaignConfirm(r.token, ok); doc = res.doc; paint(); done(ok ? t('campaign.applied', { action: r.action, file: r.where }) : t('campaign.noChange')); if (res.export) out.append(exportLine(t('export.campaign'), res.export)); }
      catch (e) { out.replaceChildren(h('p', { class: 'field__error', role: 'alert' }, e.message)); }
    };
    out.replaceChildren(h('div', { class: 'card approval-mini stack', role: 'group', 'aria-label': t('campaign.applyQ') },
      h('div', { class: 'row' }, h('b', null, t('campaign.applyQ')), chip(t('campaign.sectionApproved'), { tone: 'sage', icon: 'lock' })),
      h('p', null, t('campaign.action'), ': ', r.action, h('br'), t('campaign.where'), ': ', h('code', null, r.where)),
      h('div', { class: 'muted' }, t('campaign.before')), h('div', { class: 'diff diff--del', dir: 'auto' }, r.before ?? t('campaign.nothing')),
      h('div', { class: 'muted' }, t('campaign.after')), h('div', { class: 'diff diff--add', dir: 'auto' }, r.after ?? t('campaign.removed')),
      h('div', { class: 'row' }, button(`${t('common.refuse')} (n)`, { onClick: () => decide(false) }), button(`${t('campaign.apply')} (y)`, { variant: 'primary', onClick: () => decide(true) }))));
  }

  ask.addEventListener('click', async () => {
    if (!request.value.trim()) return request.focus();
    ask.disabled = true; out.replaceChildren(h('p', { class: 'muted', role: 'status' }, t('campaign.asking')));
    try {
      const r = await api.campaignEdit(which.value, request.value);
      if (r.status === 'confirm') confirmCard(r);
      else { doc = r.doc; selected = which.value; paint(); request.value = ''; done(t('campaign.applied', { action: r.action, file: r.where })); if (r.export) out.append(exportLine(t('export.campaign'), r.export)); }
    } catch (e) { out.replaceChildren(h('p', { class: 'field__error', role: 'alert' }, e.message)); }
    finally { ask.disabled = false; }
  });
  request.addEventListener('keydown', (e) => { if (e.key === 'Enter') ask.click(); });

  api.campaign().then((d) => { doc = d; paint(); }).catch((e) => body.replaceChildren(h('p', { class: 'field__error' }, e.message)));
}
