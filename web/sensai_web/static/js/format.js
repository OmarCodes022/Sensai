// Pure formatters. Unknown values (null/undefined) are "n/a", never 0.
import { t, getLang } from './i18n.js';

const NA = () => t('common.na');
const known = (v) => typeof v === 'number' && Number.isFinite(v);
const loc = () => (getLang() === 'fr' ? 'fr-FR' : 'en-GB');

export function formatNumber(n, digits = 0) {
  if (!known(n)) return NA();
  return new Intl.NumberFormat(loc(), { maximumFractionDigits: digits, minimumFractionDigits: digits }).format(n);
}

export function formatPercent(n, digits = 1) {
  return known(n) ? `${formatNumber(n, digits)}%` : NA();
}

/** 212 in / 85 out, "tokens n/a", or "n/a in / 85 out". */
export function formatTokens(prompt, output) {
  if (!known(prompt) && !known(output)) return t('usage.tokensNa');
  return t('usage.inOut', { in: formatNumber(prompt), out: formatNumber(output) });
}

export function formatDuration(ms) {
  if (!known(ms)) return NA();
  if (ms < 1000) return `${Math.round(ms)} ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(s < 10 ? 1 : 0)} s`;
  return `${Math.floor(s / 60)} min ${Math.round(s % 60)} s`;
}

const pad = (n) => String(n).padStart(2, '0');
export function formatUtc(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return NA();
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())} UTC`;
}

export function formatClock(iso) {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? NA() : `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function formatDate(iso) {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? NA() : new Intl.DateTimeFormat(loc(), { day: 'numeric', month: 'short', year: 'numeric' }).format(d);
}

export function relativeTime(iso, now = Date.now()) {
  const ms = new Date(iso).getTime();
  if (Number.isNaN(ms)) return NA();
  const diff = Math.max(0, Math.round((now - ms) / 1000));
  if (diff < 60) return t('time.justNow');
  const units = [[86400, 'time.days'], [3600, 'time.hours'], [60, 'time.minutes']];
  for (const [sec, key] of units) if (diff >= sec) return t(key, { n: Math.floor(diff / sec) });
  return NA();
}

/** Day bucket for sidebar grouping: Today, Yesterday, This week, then "October 2026". */
export function dayGroup(iso, now = new Date()) {
  const d = new Date(iso);
  const start = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const days = Math.round((start(now) - start(d)) / 86400000);
  if (days <= 0) return t('time.today');
  if (days === 1) return t('time.yesterday');
  if (days < 7) return t('time.thisWeek');
  return new Intl.DateTimeFormat(loc(), { month: 'long', year: 'numeric' }).format(d);
}

export function truncateMiddle(s, max = 24) {
  if (s.length <= max) return s;
  const keep = Math.floor((max - 1) / 2);
  return `${s.slice(0, keep)}…${s.slice(s.length - keep)}`;
}

export function formatBytes(n) {
  if (!known(n)) return NA();
  if (n < 1024) return `${n} B`;
  return n < 1048576 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1048576).toFixed(1)} MB`;
}

export function wordCount(text) {
  return (text.trim().match(/\S+/g) || []).length;
}
