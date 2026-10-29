// Classic blocking script in <head>: sets the theme before first paint (no flash).
(function () {
  try {
    var p = JSON.parse(localStorage.getItem('sensai.prefs') || '{}');
    var r = document.documentElement;
    if (p.theme === 'light' || p.theme === 'dark') r.setAttribute('data-theme', p.theme);
    if (p.density === 'compact') r.setAttribute('data-density', 'compact');
    if (p.fontSize && p.fontSize !== 'default') r.setAttribute('data-font', p.fontSize);
    if (p.motion === 'reduce') r.setAttribute('data-motion', 'reduce');
  } catch (e) { /* no stored prefs */ }
})();
