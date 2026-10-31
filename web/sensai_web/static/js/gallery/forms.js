import { h } from '../dom.js';
import { button, iconButton } from '../components/button.js';
import { field, input, textarea, select, toggle, check, searchField, segmented } from '../components/form.js';
import { combobox } from '../components/combobox.js';
import { kbd } from '../components/meter.js';
import { seal } from '../icons.js';

const row = (...k) => h('div', { class: 'row' }, k);

export const forms = [
  { title: 'Button', caption: 'button(label, {variant: primary|secondary|ghost|danger, size: sm|lg, icon, loading, disabled, pill, onClick}). Keyboard: Enter/Space. ARIA: native button, aria-busy while loading, icon-only buttons need aria-label (also the tooltip).',
    build: () => h('div', { class: 'stack' },
      row(button('Primary', { variant: 'primary' }), button('Secondary'), button('Ghost', { variant: 'ghost' }), button('Danger', { variant: 'danger' })),
      row(button('Disabled', { variant: 'primary', disabled: true }), button('Disabled', { disabled: true }), button('Loading', { variant: 'primary', loading: true }), button('Loading', { loading: true })),
      row(button('Small', { size: 'sm' }), button('Medium'), button('Large', { size: 'lg' }), button('With icon', { icon: 'send', variant: 'primary' }), button('Pill', { pill: true })),
      row(iconButton('copy', 'Copy'), iconButton('settings', 'Settings', { variant: 'ghost' }), iconButton('trash', 'Remove', { variant: 'danger' }), iconButton('plus', 'Add', { size: 'sm' }), iconButton('send', 'Send', { variant: 'primary', size: 'lg' }))) },
  { title: 'Link, kbd, seal', caption: 'Native <a>. kbd() renders <kbd> keys. seal() is the hanko mark (decorative, aria-hidden).',
    build: () => row(h('a', { href: '#top' }, 'A link'), ...kbd('Ctrl', 'K'), ...kbd('Shift', 'Enter'), seal(), h('span', { class: 'avatar' }, 'A'), h('span', { class: 'avatar avatar--lg', dataset: { tone: 'teal' } }, 'R')) },
  { title: 'Text input, textarea, search', caption: 'field(label, control, {help, error}) links label, help and error (aria-describedby, aria-invalid). Search field has a clear button. Textarea auto-grow is added by the composer.',
    build: () => h('div', { class: 'stack' },
      field('Name', input({ placeholder: 'Nadia' }), { help: 'Shown in the greeting.' }),
      field('Disabled', input({ value: 'Read only', disabled: true })),
      field('With error', input({ value: 'bad' }), { error: 'This value is not valid.' }),
      field('Message', textarea({ placeholder: 'Message Sensai' })),
      searchField({ placeholder: 'Search title or ID' })) },
  { title: 'Select, toggle, checkbox, radio', caption: 'Native select styled. Toggle is a checkbox with role=switch (Space). Checkbox/radio are native inputs; radios arrow-navigate natively.',
    build: () => h('div', { class: 'stack' },
      field('Density', select([['comfortable', 'Comfortable'], ['compact', 'Compact']])),
      row(toggle('Off'), toggle('On', { checked: true }), toggle('Disabled', { disabled: true })),
      row(check('Unchecked'), check('Checked', { checked: true }), check('Indeterminate', { indeterminate: true }), check('Disabled', { disabled: true })),
      row(check('One', { type: 'radio', name: 'g1', checked: true }), check('Two', { type: 'radio', name: 'g1' }), check('Disabled', { type: 'radio', name: 'g1', disabled: true }))) },
  { title: 'Segmented control, combobox', caption: 'Segmented: radiogroup with roving tabindex (arrows). Combobox: ARIA 1.2, aria-activedescendant, Up/Down/Enter/Esc, listbox popup.',
    build: () => h('div', { class: 'stack' },
      segmented('Font size', [['small', 'Small'], ['default', 'Default'], ['large', 'Large']], 'default'),
      combobox({ label: 'Persona', placeholder: 'Choose a persona', options: [{ value: 'redaction', label: 'Rédaction' }, { value: 'communaute', label: 'Communauté' }, { value: 'analyse', label: 'Analyse' }, { value: 'x', label: 'Disabled option', disabled: true }] })) },
];
