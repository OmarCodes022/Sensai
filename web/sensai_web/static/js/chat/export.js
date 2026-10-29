// Client-side transcript export: Markdown text, download, print.
import { formatUtc } from '../format.js';
import { stripInvisible } from '../safetext.js';
import { t } from '../i18n.js';

/** items: model items (user / assistant / event). Interrupted replies are left out like the saved history. */
export function toMarkdown(session, items) {
  const title = session?.title ? stripInvisible(session.title) : t('session.new');
  const out = [`# ${title}`, '', `${t('export.session')}: ${session?.id || ''}`, `${t('export.date')}: ${formatUtc(new Date().toISOString())}`, ''];
  for (const it of items) {
    if (it.kind === 'user' && it.n) out.push(`### ${t('export.you')} (#${it.n})`, '', it.text, '');
    else if (it.kind === 'assistant' && !it.interrupted) {
      out.push(`### ${it.persona || t('export.assistant')}`, '');
      for (const tool of it.tools || []) out.push(`> ${t('tool.using')} ${tool.name}: ${JSON.stringify(tool.arguments ?? {})}`);
      if (it.tools?.length) out.push('');
      out.push(it.text, '');
    } else if (it.kind === 'event') out.push(`*${it.text}*`, '');
  }
  return out.join('\n').replace(/\n{3,}/g, '\n\n').trim() + '\n';
}

export function downloadText(name, text) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([text], { type: 'text/markdown;charset=utf-8' }));
  a.download = name;
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
