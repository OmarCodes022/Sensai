// Beats of a keynote scenario: one beat per scripted turn. Prompts are what the presenter's "user" sends.
import { SCENARIOS } from '../mock/scenarios.js';

const MONDAY = ['Summarise last week for me', 'Write 3 post drafts using only approved claims', 'Suggest replies to this week\'s DMs', '/campaign posts make P2 more playful', 'What works, and what are the limits?'];

export const playable = () => SCENARIOS.filter((s) => s.turns.length > 0);
export const promptFor = (sc, i) => (sc.id === 'monday' ? MONDAY[i] : i === 0 ? sc.prompt : 'Please continue');
export const notesOf = (sc) => (Array.isArray(sc.notes) ? sc.notes : sc.notes ? [sc.notes] : []);
