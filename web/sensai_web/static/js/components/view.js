// Shared helpers for full-page views: titled shell and a loading/error wrapper.
import { h } from '../dom.js';
import { errorState, skeletonRows } from './state.js';
import { t } from '../i18n.js';

/** Sets the tab title and returns .view with one h1. */
export function viewShell(name, ...kids) {
  const title = t(`nav.${name}`);
  document.title = `${title} - Sensai`;
  return h('div', { class: 'view' }, h('h1', null, title), ...kids);
}

/** Shows a skeleton, awaits load(), then render(data). A failure shows an error state with Retry. Ignores results after unmount. */
export async function loadInto(box, load, render, errorTitle = t('common.loadError')) {
  box.replaceChildren(skeletonRows(3));
  try {
    const data = await load();
    if (box.isConnected) render(data);
  } catch (e) {
    if (box.isConnected) box.replaceChildren(errorState({ title: errorTitle, body: e.message, onRetry: () => loadInto(box, load, render, errorTitle) }));
  }
}

export const section = (title, ...kids) => h('section', { class: 'stack vsec' }, h('h2', null, title), ...kids);
