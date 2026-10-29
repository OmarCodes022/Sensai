import { h } from '../dom.js';
import { icon } from '../icons.js';
import { announce } from '../a11y.js';
import { t } from '../i18n.js';

export async function copyText(text) {
  try { await navigator.clipboard.writeText(text); return true; }
  catch {
    const ta = h('textarea', { 'aria-hidden': 'true' });
    ta.value = text;
    document.body.append(ta);
    ta.select();
    let ok = false;
    try { ok = document.execCommand('copy'); } catch { /* blocked */ }
    ta.remove();
    return ok;
  }
}

/** Button that copies getText() and shows a check icon for 1.2 s. */
export function copyButton(getText, { label = t('common.copy'), small = true, text = false } = {}) {
  const btn = h('button', { type: 'button', class: `btn btn--ghost ${small ? 'btn--sm' : ''} ${text ? '' : 'btn--icon'}`, 'aria-label': label, 'data-tip': label }, icon('copy', { size: 16 }), text ? label : null);
  btn.addEventListener('click', async () => {
    const ok = await copyText(getText());
    announce(ok ? t('common.copied') : t('common.copyFailed'));
    if (!ok) return;
    btn.replaceChildren(icon('check', { size: 16 }), ...(text ? [t('common.copied')] : []));
    setTimeout(() => btn.replaceChildren(icon('copy', { size: 16 }), ...(text ? [label] : [])), 1200);
  });
  return btn;
}
