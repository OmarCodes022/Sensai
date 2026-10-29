export const isMac = (() => {
  try { return /mac|iphone|ipad/i.test(navigator.userAgentData?.platform || navigator.platform || ''); } catch { return false; }
})();
export const modKey = () => (isMac ? 'Cmd' : 'Ctrl');
/** True when the platform modifier (Cmd on macOS, Ctrl elsewhere) is held. */
export const hasMod = (e) => (isMac ? e.metaKey : e.ctrlKey);
