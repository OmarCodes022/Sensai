// Minimal i18n: flat JSON dictionaries, {name} interpolation, English fallback.
const dicts = {};
let lang = 'en';

async function load(l) {
  if (dicts[l]) return dicts[l];
  try {
    const res = await fetch(new URL(`./strings.${l}.json`, import.meta.url));
    dicts[l] = res.ok ? await res.json() : {};
  } catch { dicts[l] = {}; }
  return dicts[l];
}

export async function setLang(l) {
  await load('en');
  if (l !== 'en') await load(l);
  lang = l;
  document.documentElement.lang = l;
}

export const getLang = () => lang;

export function t(key, vars) {
  const raw = dicts[lang]?.[key] ?? dicts.en?.[key] ?? key;
  return vars ? raw.replace(/\{(\w+)\}/g, (m, k) => (k in vars ? vars[k] : m)) : raw;
}
