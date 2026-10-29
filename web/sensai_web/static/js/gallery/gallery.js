// Component gallery: every primitive in every state, light and dark side by side.
import { h } from '../dom.js';
import { loadPrefs, applyPrefs } from '../prefs.js';
import { setLang } from '../i18n.js';
import { initTooltips } from '../components/tooltip.js';
import { seal } from '../icons.js';
import { forms } from './forms.js';
import { display } from './display.js';
import { overlays } from './overlays.js';

const SECTIONS = [...forms, ...display, ...overlays];

function pane(scheme, build) {
  const el = h('div', { class: 'gallery-pane', 'data-scheme': scheme }, h('span', { class: 'chip chip--outline' }, scheme), build());
  el.style.setProperty('color-scheme', scheme);
  return el;
}

async function boot() {
  const prefs = loadPrefs();
  applyPrefs(prefs);
  await setLang(prefs.lang);
  initTooltips();
  const page = h('div', { class: 'gallery' },
    h('header', { class: 'row' }, seal(), h('h1', null, 'Sensai component gallery')),
    h('p', { class: 'muted' }, 'Each component is shown in the light and dark theme. Use Tab to see focus rings; hover for hover states.'),
    SECTIONS.map((s, i) => h('section', { 'aria-labelledby': `g${i}` }, h('h2', { id: `g${i}` }, s.title), h('p', { class: 'muted' }, s.caption),
      h('div', { class: 'gallery-cols' }, pane('light', s.build), pane('dark', s.build)))));
  document.getElementById('app').replaceChildren(page);
}
boot();
