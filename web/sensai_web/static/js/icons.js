// Inline SVG icon set: 20px grid, 1.5px stroke, currentColor.
// Shape DSL: "o cx cy r" circle, "r x y w h rx" rect, otherwise a path "d"; shapes joined with " | ".
const SUN = 'M10 2.5v2M10 15.5v2M2.5 10h2M15.5 10h2M4.7 4.7l1.4 1.4M13.9 13.9l1.4 1.4M4.7 15.3l1.4-1.4M13.9 6.1l1.4-1.4';
const SHIELD = 'M10 2.5l6 2v5c0 4-2.6 6.5-6 8-3.4-1.5-6-4-6-8v-5z';
const FILE = 'M5 3h6l4 4v10H5z | M11 3v4h4';
const DATA = {
  chat: 'M4 5h12a1 1 0 0 1 1 1v7a1 1 0 0 1-1 1H9l-4 3v-3H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z',
  plus: 'M10 4v12M4 10h12',
  search: 'o 9 9 5 | M13 13l4 4',
  send: 'M17 3L3 9.5l6 2.5 2.5 6z | M9 12l8-9',
  stop: 'r 5 5 10 10 1.5',
  history: 'M4 10a6 6 0 1 0 2-4.5M4 4v3h3 | M10 7v3.5l2.5 1.5',
  user: 'o 10 7 3 | M4 17c0-3.3 2.7-5 6-5s6 1.7 6 5',
  persona: 'o 7 7 2.5 | M2.5 16c0-2.8 2-4.2 4.5-4.2s4.5 1.4 4.5 4.2 | o 14 8 2 | M13 12.2c2.2-.2 4.5 1 4.5 3.8',
  tools: 'r 3 7 14 9 2 | M7 7V5.5A1.5 1.5 0 0 1 8.5 4h3A1.5 1.5 0 0 1 13 5.5V7 | M3 11h14',
  wrench: 'M13.5 3.5a3.5 3.5 0 0 0-3.4 4.5L3.5 14.6a1.4 1.4 0 0 0 2 2L12 10a3.5 3.5 0 0 0 4.5-3.4l-2 2-2-.5-.5-2z',
  code: 'M7 6l-4 4 4 4M13 6l4 4-4 4',
  play: 'M7 4.5v11l9-5.5z',
  shield: SHIELD,
  'shield-check': `${SHIELD} | M7 10l2 2 4-4`,
  lock: 'r 4 9 12 8 2 | M7 9V6.5a3 3 0 0 1 6 0V9',
  unlock: 'r 4 9 12 8 2 | M7 9V6.5a3 3 0 0 1 5.8-1',
  eye: 'M2 10s3-5.5 8-5.5S18 10 18 10s-3 5.5-8 5.5S2 10 2 10z | o 10 10 2.5',
  'eye-off': 'M3 3l14 14 | M8 4.6a8 8 0 0 1 2-.1c5 0 8 5.5 8 5.5a14 14 0 0 1-2.5 3M5.5 6.5A13 13 0 0 0 2 10s3 5.5 8 5.5c1 0 1.9-.2 2.8-.5',
  copy: 'r 7 7 9 9 1.5 | M13 7V5.5A1.5 1.5 0 0 0 11.5 4h-6A1.5 1.5 0 0 0 4 5.5v6A1.5 1.5 0 0 0 5.5 13H7',
  check: 'M4 10.5l4 4 8-9',
  'check-circle': 'o 10 10 7.5 | M6.5 10l2.5 2.5 4.5-5',
  x: 'M5 5l10 10M15 5L5 15',
  'x-circle': 'o 10 10 7.5 | M7.5 7.5l5 5M12.5 7.5l-5 5',
  'alert-triangle': 'M10 3l8 14H2z | M10 8v4 | M10 14.5v.01',
  info: 'o 10 10 7.5 | M10 9v5 | M10 6.5v.01',
  clock: 'o 10 10 7.5 | M10 6v4l3 2',
  pause: 'M7 5v10M13 5v10',
  refresh: 'M16 10a6 6 0 1 1-1.8-4.3M16 3.5v3h-3',
  download: 'M10 3v10M6 9l4 4 4-4M4 16h12',
  upload: 'M10 13V3M6 7l4-4 4 4M4 16h12',
  link: 'M8.5 11.5a3 3 0 0 0 4.2 0l3-3a3 3 0 0 0-4.2-4.2l-1 1 | M11.5 8.5a3 3 0 0 0-4.2 0l-3 3a3 3 0 0 0 4.2 4.2l1-1',
  'external-link': 'M8 4H5a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1v-3 | M11 3h6v6 | M17 3l-8 8',
  file: FILE,
  'file-text': `${FILE} | M7.5 11h5M7.5 14h5`,
  folder: 'M3 6a1 1 0 0 1 1-1h4l2 2h6a1 1 0 0 1 1 1v7a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z',
  database: 'M4 5.5C4 4.4 6.7 3.5 10 3.5s6 .9 6 2-2.7 2-6 2-6-.9-6-2z | M4 5.5v9c0 1.1 2.7 2 6 2s6-.9 6-2v-9 | M4 10c0 1.1 2.7 2 6 2s6-.9 6-2',
  chart: 'M4 16V9M10 16V4M16 16v-5',
  calendar: 'r 3 4.5 14 12 2 | M3 8.5h14M7 3v3M13 3v3',
  grid: 'r 3 3 5.5 5.5 1 | r 11.5 3 5.5 5.5 1 | r 3 11.5 5.5 5.5 1 | r 11.5 11.5 5.5 5.5 1',
  list: 'M7 5h10M7 10h10M7 15h10M3.5 5h.01M3.5 10h.01M3.5 15h.01',
  settings: 'o 10 10 2.5 | M8.5 2.5h3l.5 2 1.5.9 2-.7 1.5 2.6-1.5 1.4v1.8l1.5 1.4-1.5 2.6-2-.7-1.5.9-.5 2h-3l-.5-2-1.5-.9-2 .7L2.5 13.5 4 12.1v-1.8L2.5 8.9 4 6.3l2 .7 1.5-.9z',
  sliders: 'M4 6h12M4 14h12 | o 8 6 1.8 | o 12 14 1.8',
  sun: `o 10 10 3.5 | ${SUN}`,
  moon: 'M16 11.5A6.5 6.5 0 0 1 8.5 4a6.5 6.5 0 1 0 7.5 7.5z',
  command: 'M7 7h6v6H7z | M7 7V5.5A1.5 1.5 0 1 0 5.5 7H7M13 7h1.5A1.5 1.5 0 1 0 13 5.5V7M7 13H5.5A1.5 1.5 0 1 0 7 14.5V13M13 13v1.5a1.5 1.5 0 1 0 1.5-1.5H13',
  keyboard: 'r 2 5 16 10 2 | M5.5 8.5h.01M8.5 8.5h.01M11.5 8.5h.01M14.5 8.5h.01 | M6 12h8',
  'panel-left': 'r 3 4 14 12 2 | M8 4v12',
  'panel-right': 'r 3 4 14 12 2 | M12 4v12',
  branch: 'o 6 5 1.8 | o 6 15 1.8 | o 14 8 1.8 | M6 6.8v6.4 | M14 9.8c0 3-8 1.5-8 3.4',
  star: 'M10 2.5c.6 4.4 2.6 6.4 7 7-4.4.6-6.4 2.6-7 7-.6-4.4-2.6-6.4-7-7 4.4-.6 6.4-2.6 7-7z',
  map: 'M3 5l4-1.5 6 2L17 4v11l-4 1.5-6-2L3 16z | M7 3.5v11M13 5.5v11',
  flag: 'M5 17V3.5 | M5 4h9l-2 3 2 3H5',
  trash: 'M4 6h12M8 6V4h4v2M6 6l.7 10h6.6L14 6',
  edit: 'M12.5 4.5l3 3L7 16H4v-3z',
  'more-horizontal': 'o 4.5 10 .8 | o 10 10 .8 | o 15.5 10 .8',
  'chevron-up': 'M5 12l5-5 5 5',
  'chevron-down': 'M5 8l5 5 5-5',
  'chevron-left': 'M12 5l-5 5 5 5',
  'chevron-right': 'M8 5l5 5-5 5',
  'drag-handle': 'M7 5h.01M13 5h.01M7 10h.01M13 10h.01M7 15h.01M13 15h.01',
};
export const ICON_NAMES = Object.keys(DATA);
const NS = 'http://www.w3.org/2000/svg';

function shape(spec) {
  const [kind, ...n] = spec.split(' ');
  const mk = (tag, attrs) => {
    const el = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
    return el;
  };
  if (kind === 'o') return mk('circle', { cx: n[0], cy: n[1], r: n[2] });
  if (kind === 'r') return mk('rect', { x: n[0], y: n[1], width: n[2], height: n[3], rx: n[4] });
  return mk('path', { d: spec });
}

/** icon('check', {size: 16, label: 'Saved'}): decorative unless label is given. */
export function icon(name, { size = 20, label } = {}) {
  const spec = DATA[name];
  const svg = document.createElementNS(NS, 'svg');
  for (const [k, v] of Object.entries({ width: size, height: size, viewBox: '0 0 20 20', fill: 'none', stroke: 'currentColor', 'stroke-width': 1.5, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' })) svg.setAttribute(k, v);
  if (label) { svg.setAttribute('role', 'img'); svg.setAttribute('aria-label', label); }
  else svg.setAttribute('aria-hidden', 'true');
  if (spec) for (const s of spec.split(' | ')) svg.append(shape(s.trim()));
  return svg;
}

/** The hanko seal: a text glyph with system CJK fallback, hidden from assistive tech. */
export function seal() {
  const s = document.createElement('span');
  s.className = 'seal';
  s.setAttribute('aria-hidden', 'true');
  s.textContent = '先';
  return s;
}
