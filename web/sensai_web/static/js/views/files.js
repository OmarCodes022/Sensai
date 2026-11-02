// Notes and file access (T4): the notes the creator writes, and the rules for what Sensai may read and save.
import { viewShell, section } from '../components/view.js';
import { createNotesCard } from '../files/notes.js';
import { createRulesCard } from '../files/rules.js';
import { t } from '../i18n.js';

export function mount(root, { api }) {
  root.append(viewShell('files', section(t('notes.title'), createNotesCard({ api }).el), section(t('rules.title'), createRulesCard({ api }).el)));
}
