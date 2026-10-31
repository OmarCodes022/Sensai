// Transcript overflow menu (spec 6.13): copy, download, print, display toggles, jump to message, planned export.
import { h } from '../dom.js';
import { icon } from '../icons.js';
import { iconButton } from '../components/button.js';
import { openPopover } from '../components/popover.js';
import { openModal } from '../components/modal.js';
import { copyText } from '../components/copy-button.js';
import { toast } from '../components/toast.js';
import { announce } from '../a11y.js';
import { toMarkdown, downloadText } from './export.js';
import { t } from '../i18n.js';

/** deps: { store, actions, model, jump(n) } */
export function createMenu({ store, actions, model, jump }) {
  const btn = iconButton('more-horizontal', t('menu.title'), { variant: 'ghost', 'aria-haspopup': 'menu', 'aria-expanded': 'false' });
  const md = () => toMarkdown(store.get().session, model.items);
  const item = (label, ic, fn, extra = {}) => h('button', { type: 'button', class: 'menu-item', role: extra.role || 'menuitem', 'aria-checked': extra.checked, 'aria-disabled': extra.disabled ? 'true' : null,
    onclick: () => { if (extra.disabled) return; pop.close(); fn(); } }, icon(ic, { size: 16 }), h('span', { class: 'grow' }, label), extra.chip || null);
  let pop;
  btn.addEventListener('click', () => {
    const p = store.get().prefs;
    pop = openPopover(btn, [
      item(t('menu.copyMd'), 'copy', async () => { const ok = await copyText(md()); toast(ok ? t('common.copied') : t('common.copyFailed')); announce(ok ? t('common.copied') : t('common.copyFailed')); }),
      item(t('menu.download'), 'download', () => downloadText(`sensai-${store.get().session?.id || 'chat'}.md`, md())),
      item(t('menu.print'), 'file-text', () => print()),
      item(p.showTools ? t('menu.hideTools') : t('menu.showTools'), 'tools', () => actions.setPref('showTools', !p.showTools)),
      item(p.showTokens ? t('menu.hideTokens') : t('menu.showTokens'), 'chart', () => actions.setPref('showTokens', !p.showTokens)),
      item(t('menu.jump'), 'search', () => askJump()),
      item(t('menu.serverExport'), 'folder', () => {}, { disabled: true, chip: h('span', { class: 'chip chip--outline' }, `${t('common.planned')} T50`) }),
    ], { menu: true, label: t('menu.title') });
  });
  function askJump() {
    const input = h('input', { class: 'input', type: 'number', min: 1, 'aria-label': t('menu.jumpLabel') });
    const go = (close) => { const n = Number(input.value); if (n >= 1) { close(); jump(n); } };
    const m = openModal({ title: t('menu.jump'), body: input, actions: [{ label: t('common.cancel') }, { label: t('menu.go'), variant: 'primary', onClick: go }] });
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); go(m.close); } });
    input.focus();
  }
  return btn;
}
