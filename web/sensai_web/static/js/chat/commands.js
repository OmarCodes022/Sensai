// Slash commands exactly as spec 6.4. Live ones run; planned ones are dimmed with their task ID.
export const COMMANDS = [
  { name: 'persona', live: true }, { name: 'history', live: true }, { name: 'tools', live: true },
  { name: 'run', live: true }, { name: 'new', live: true }, { name: 'help', live: true },
  { name: 'add', task: 'T36', cap: 'documents' }, { name: 'remove', task: 'T36', cap: 'documents' },
  { name: 'docs', task: 'T36', cap: 'documents' }, { name: 'reindex', task: 'T36', cap: 'documents' },
  { name: 'read', task: 'T26' }, { name: 'save', task: 'T26' },
  { name: 'search', task: 'T41' }, { name: 'facts', task: 'T32' }, { name: 'context', task: 'T31' }, { name: 'campaign', task: 'T40' },
  { name: 'export', task: 'T50' }, { name: 'share', task: 'T53' }, { name: 'unshare', task: 'T53' }, { name: 'think', task: 'T20', cap: 'think' },
  { name: 'team', task: 'T48' }, { name: 'edit', task: 'T34', cap: 'branching' },
];

/** A command is live when it is wired today, or when the capability that turns it on is true. */
const withLive = (caps) => COMMANDS.map((c) => ({ ...c, live: !!(c.live || (c.cap && caps?.[c.cap])) }));

/** Prefix matches first, then substring matches. q is the text after the slash. */
export function matchCommands(q, caps) {
  const s = q.toLowerCase();
  const all = withLive(caps);
  const pre = all.filter((c) => c.name.startsWith(s));
  return [...pre, ...all.filter((c) => !pre.includes(c) && s && c.name.includes(s))];
}

export const findCommand = (word, caps) => withLive(caps).find((c) => c.name === word.toLowerCase());
