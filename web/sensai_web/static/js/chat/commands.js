// Slash commands exactly as spec 6.4. Live ones run; planned ones are dimmed with their task ID.
export const COMMANDS = [
  { name: 'persona', live: true }, { name: 'history', live: true }, { name: 'tools', live: true },
  { name: 'run', live: true }, { name: 'new', live: true }, { name: 'help', live: true },
  { name: 'read', task: 'T26' }, { name: 'save', task: 'T26' }, { name: 'docs', task: 'T36' }, { name: 'reindex', task: 'T36' },
  { name: 'search', task: 'T41' }, { name: 'facts', task: 'T32' }, { name: 'context', task: 'T31' }, { name: 'campaign', task: 'T40' },
  { name: 'export', task: 'T50' }, { name: 'share', task: 'T53' }, { name: 'unshare', task: 'T53' }, { name: 'think', task: 'T20' },
  { name: 'team', task: 'T48' }, { name: 'edit', task: 'T34' },
];

/** Prefix matches first, then substring matches. q is the text after the slash. */
export function matchCommands(q) {
  const s = q.toLowerCase();
  const pre = COMMANDS.filter((c) => c.name.startsWith(s));
  return [...pre, ...COMMANDS.filter((c) => !pre.includes(c) && s && c.name.includes(s))];
}

export const findCommand = (word) => COMMANDS.find((c) => c.name === word.toLowerCase());
