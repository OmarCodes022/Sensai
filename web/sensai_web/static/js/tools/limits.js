// Sandbox limit chips with a "?" popover: what each limit means and what the sandbox does NOT protect against.
import { h } from '../dom.js';
import { chip } from '../components/chip.js';
import { openPopover } from '../components/popover.js';
import { t } from '../i18n.js';

const NOT = ['malicious', 'network', 'absolute', 'memory', 'cpu', 'fork', 'group', 'kill'];

export function limitChips(lim) {
  const l = { wall_seconds: 15, cpu_seconds: 10, memory_mb: 512, file_mb: 10, output_chars: 10000, ...(lim || {}) };
  const help = h('button', { type: 'button', class: 'btn btn--ghost btn--sm btn--icon', 'aria-haspopup': 'dialog', 'aria-expanded': 'false', 'aria-label': t('tools.limitsHelp') }, '?');
  help.addEventListener('click', () => openPopover(help, h('div', { class: 'stack limits-help' },
    h('h3', null, t('tools.limitsTitle')),
    h('dl', { class: 'kv' }, ['wall', 'cpu', 'mem', 'file', 'out'].flatMap((k) => [h('dt', null, t(`tools.limit.${k}`)), h('dd', null, t(`tools.limit.${k}.d`))])),
    h('h3', null, t('tools.notProtected')), h('ul', { class: 'bullets' }, NOT.map((k) => h('li', null, t(`tools.not.${k}`))))), { label: t('tools.limitsTitle') }));
  return h('div', { class: 'row' },
    chip(`${l.wall_seconds} s`, { outline: true }), chip(`${l.cpu_seconds} s CPU`, { outline: true }), chip(`${l.memory_mb} MB`, { outline: true }),
    chip(`${l.file_mb} MB file`, { outline: true }), chip(`${l.output_chars} chars`, { outline: true }), help);
}
