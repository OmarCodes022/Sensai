// Pick files from the computer and read them as UTF-8 text with the same checks everywhere.
import { formatBytes } from '../format.js';
import { t } from '../i18n.js';

/** Opens the file dialog; resolves with the chosen files (an empty list if it is cancelled). */
export function pickFiles({ accept = '', multiple = true } = {}) {
  return new Promise((resolve) => {
    const input = document.createElement('input');
    Object.assign(input, { type: 'file', multiple, accept });
    input.style.setProperty('display', 'none');
    input.addEventListener('change', () => { resolve([...input.files]); input.remove(); });
    input.addEventListener('cancel', () => { resolve([]); input.remove(); });
    document.body.append(input);
    input.click();
  });
}

/** The file's text, or an Error whose message says what is wrong (type, size or not text). */
export async function readTextFile(file, { types, maxMb, keys }) {
  const dot = file.name.lastIndexOf('.');
  const ext = dot < 0 ? '' : file.name.slice(dot).toLowerCase();
  if (!types.includes(ext)) throw new Error(t(keys.badType, { name: file.name, types: types.join(', ') }));
  if (file.size > maxMb * 1048576) throw new Error(t(keys.tooBig, { name: file.name, mb: maxMb, size: formatBytes(file.size) }));
  try { return new TextDecoder('utf-8', { fatal: true }).decode(await file.arrayBuffer()); } catch { throw new Error(t(keys.notText, { name: file.name })); }
}
