import { h } from '../dom.js';
import { icon, ICON_NAMES } from '../icons.js';
import { chip, statusDot } from '../components/chip.js';
import { meter, progressBar, progressRing, spinner, skeleton } from '../components/meter.js';
import { banner } from '../components/banners.js';
import { emptyState, errorState } from '../components/state.js';
import { tabs } from '../components/tabs.js';
import { codeBlock } from '../components/code-block.js';
import { renderMarkdown } from '../markdown.js';

const row = (...k) => h('div', { class: 'row' }, k);
const SAMPLE = '## Heading\n\nSome **bold**, *italic*, `code` and a [link](https://example.com).\n\n- one\n  - nested\n- two\n\n| Metric | Value |\n|---|---:|\n| Reached | 4,200 |\n\n```py\nprint(630 / 4200 * 100)\n```\n\n<script>alert(1)</script>';

export const display = [
  { title: 'Chip and status dot', caption: 'chip(text, {tone, icon, mono, outline, onRemove}). Tones carry meaning (accent brand, sage ok, amber draft/pending, rose error, teal tools, plum privacy). Never color alone: always text or icon.',
    build: () => h('div', { class: 'stack' },
      row(chip('Neutral'), chip('Accent', { tone: 'accent' }), chip('Approved', { tone: 'sage', icon: 'check' }), chip('Draft', { tone: 'amber', icon: 'clock' }), chip('Refused', { tone: 'rose', icon: 'x' }), chip('Tool', { tone: 'teal', icon: 'tools' }), chip('Privacy', { tone: 'plum', icon: 'shield' })),
      row(chip('gemma3:1b', { mono: true }), chip('Outline', { outline: true }), chip('Removable', { onRemove: () => {} })),
      row(h('span', { class: 'row' }, statusDot('sage'), 'Ready'), h('span', { class: 'row' }, statusDot('amber'), 'Checking'), h('span', { class: 'row' }, statusDot('rose'), 'Offline'))) },
  { title: 'Spinner, skeleton, progress, ring', caption: 'Spinner and skeleton are decorative (aria-hidden) unless a label is passed. Progress bar and ring expose role=progressbar with values. Motion stops under reduced motion.',
    build: () => h('div', { class: 'stack' }, row(spinner(), spinner('Loading')), skeleton('60%'), skeleton('40%'), progressBar(45), row(progressRing(25, 'Turn budget'), progressRing(75, 'Turn budget'))) },
  { title: 'Meter', caption: 'meter({value, max, marker}): role=meter plus a text alternative. sage under 60%, amber 60-85, rose above 85. marker shows the 80% budget line.',
    build: () => h('div', { class: 'stack' }, meter({ value: 1262, max: 4096 }), meter({ value: 3000, max: 4096, marker: true }), meter({ value: 3800, max: 4096 })) },
  { title: 'Banner', caption: 'banner({tone: info|warning|error, text, actions}). role=status, or role=alert for errors.',
    build: () => h('div', { class: 'stack' }, banner({ text: 'Playing recorded demo data.', inline: true }), banner({ tone: 'warning', text: 'Timer paused while you decide.', inline: true }), banner({ tone: 'error', text: 'Lost connection to Sensai.', actions: [{ label: 'Reconnect', onClick: () => {} }], inline: true })) },
  { title: 'Empty and error state', caption: 'emptyState({icon, title, body, actions}) and errorState({title, body, onRetry}). Errors use role=alert.',
    build: () => h('div', { class: 'card' }, emptyState({ icon: 'chat', title: 'No saved conversations yet', body: 'They appear here after your first completed exchange.' }), errorState({ title: 'Could not load sessions', onRetry: () => {} })) },
  { title: 'Tabs', caption: 'tabs({label, items, selected}). APG tabs: roving tabindex, arrows and Home/End move and activate, aria-controls links tab and panel.',
    build: () => tabs({ label: 'Demo', items: ['Turn', 'Context', 'Tools'].map((l) => ({ id: l, label: l, render: () => h('p', null, `${l} panel`) })) }) },
  { title: 'Table', caption: 'Sticky header, tabular numbers, aria-sort on sortable headers. Under 768 px the cards variant stacks cells with data-label.',
    build: () => h('div', { class: 'table-wrap' }, h('table', { class: 'table table--cards' }, h('thead', null, h('tr', null, h('th', { 'aria-sort': 'ascending' }, h('button', { type: 'button' }, 'Title', icon('chevron-up', { size: 12 }))), h('th', null, 'ID'), h('th', null, 'Messages'))),
      h('tbody', null, [['Weekly engagement', 'p9d3wx', 8], ['Caption ideas', 'k7f2qa', 14]].map(([a, b, c]) => h('tr', null, h('td', { 'data-label': 'Title' }, a), h('td', { class: 'mono', 'data-label': 'ID' }, b), h('td', { class: 'num', 'data-label': 'Messages' }, c)))))) },
  { title: 'Card, stat tile, mock ribbon', caption: 'Card is a plain container. Stat tile shows a metric with tabular numbers. .ribbon adds the diagonal MOCK corner for mock data.',
    build: () => row(h('div', { class: 'card' }, h('div', { class: 'card__title' }, 'Card'), h('p', { class: 'muted' }, 'Quiet surface with a hairline.')), h('div', { class: 'card stat' }, h('span', { class: 'stat__value' }, '4,200'), h('span', { class: 'stat__label' }, 'Accounts reached')), h('div', { class: 'card ribbon stat' }, h('span', { class: 'stat__value' }, '15.0%'), h('span', { class: 'stat__label' }, 'Engagement rate'))) },
  { title: 'Code block and Markdown', caption: 'codeBlock(text, lang): header with language, wrap toggle, Copy; max 480 px with Show all; Esc leaves the block. Markdown below is rendered by the safe renderer (raw HTML stays literal text).',
    build: () => h('div', null, codeBlock('import csv\nprint("hello")', 'python'), h('div', { class: 'md' }, renderMarkdown(SAMPLE))) },
  { title: `Icons (${ICON_NAMES.length})`, caption: 'icon(name, {size, label}): 20px grid, 1.5px stroke, currentColor. Decorative (aria-hidden) unless a label is given.',
    build: () => h('div', { class: 'row' }, ICON_NAMES.map((n) => h('span', { class: 'stack', 'data-tip': n, tabindex: '0' }, icon(n)))) },
];
