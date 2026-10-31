// Pane state: sidebar open|rail|closed, inspector open|closed. Overlay modes below 1280/1024 px.
export function createLayout(app, store, setPref) {
  const wideInspector = matchMedia('(min-width: 1280px)');
  const wideSidebar = matchMedia('(min-width: 1024px)');
  const prefs = store.get().prefs;
  const st = { sb: wideSidebar.matches ? prefs.sidebar : 'closed', inn: wideInspector.matches ? prefs.inspector : 'closed' };
  const listeners = new Set();

  const apply = () => {
    app.dataset.sb = st.sb;
    app.dataset.in = st.inn;
    listeners.forEach((f) => f(st));
  };
  const layout = {
    st,
    onChange: (f) => { listeners.add(f); f(st); },
    toggleSidebar() {
      st.sb = st.sb === 'open' ? (wideSidebar.matches ? 'rail' : 'closed') : 'open';
      if (wideSidebar.matches) setPref('sidebar', st.sb);
      apply();
    },
    toggleInspector() {
      st.inn = st.inn === 'open' ? 'closed' : 'open';
      if (wideInspector.matches) setPref('inspector', st.inn);
      apply();
    },
    openInspector() { if (st.inn !== 'open') layout.toggleInspector(); },
    /** Closes overlay drawers. Returns true if something was closed. */
    closeOverlays() {
      let closed = false;
      if (!wideSidebar.matches && st.sb !== 'closed') { st.sb = 'closed'; closed = true; }
      if (!wideInspector.matches && st.inn === 'open') { st.inn = 'closed'; closed = true; }
      if (closed) apply();
      return closed;
    },
  };
  wideInspector.addEventListener('change', (e) => { st.inn = e.matches ? store.get().prefs.inspector : 'closed'; apply(); });
  wideSidebar.addEventListener('change', (e) => { st.sb = e.matches ? store.get().prefs.sidebar : 'closed'; apply(); });
  apply();
  return layout;
}
