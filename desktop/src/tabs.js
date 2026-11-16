const { WebContentsView, session } = require('electron');
const path = require('node:path');

module.exports = ({ getWindow, state, views, armed, sites, notify, inject, signIns }) => {
  function bounds() {
    if (state.active && views[state.active]) {
      const [width, height] = getWindow().getContentSize();
      const top = state.active === 'sheet' ? 240 : 255;
      views[state.active].setBounds({
        x: 204,
        y: top,
        width: Math.max(0, width - 204),
        height: Math.max(0, height - top),
      });
    }
  }

  function tabState(site) {
    const view = views[site];
    if (view) notify('tab-state', { site, url: view.webContents.getURL(), armed: !!armed[site] });
  }

  function createView(site) {
    const spec = sites[site];
    const ses = session.fromPartition('persist:' + site);
    ses.setPermissionRequestHandler((_wc, _permission, cb) => cb(false));
    ses.setPermissionCheckHandler(() => false);
    const view = new WebContentsView({
      webPreferences: {
        partition: 'persist:' + site,
        preload: path.join(__dirname, '..', 'view-preload.js'),
        contextIsolation: true,
        nodeIntegration: false,
        sandbox: true,
        backgroundThrottling: false, // helper runs (eMIMS lists) must keep full timer speed when the tab is hidden
      },
    });
    views[site] = view;
    view.webContents.setWindowOpenHandler(({ url }) => {
      if (/^https?:/i.test(url)) view.webContents.loadURL(url);
      return { action: 'deny' };
    });
    view.webContents.on('will-navigate', (event, url) => {
      if (!/^https?:/i.test(url)) event.preventDefault();
    });
    for (const ev of ['did-navigate', 'did-navigate-in-page']) {
      view.webContents.on(ev, () => tabState(site));
    }
    view.webContents.on('did-start-navigation', (_event, _url, _inPlace, isMainFrame) => {
      if (isMainFrame) signIns.reset(site);
    });
    view.webContents.on('dom-ready', () => {
      tabState(site);
      if (armed[site]) inject(site).catch((e) => notify('result', { site, status: e.message }));
    });
    view.webContents.loadURL(process.env.HMR_SMOKE_URL && site === 'mhr' ? process.env.HMR_SMOKE_URL : spec.url);
    return view;
  }

  async function openTab(site) {
    if (!sites[site]) throw Error('Unknown tab');
    if (state.active && views[state.active]) getWindow().contentView.removeChildView(views[state.active]);
    state.active = site;
    const view = views[site] || createView(site);
    getWindow().contentView.addChildView(view);
    bounds();
    tabState(site);
    signIns.update(site);
  }

  function ensureView(site) { // load a tab without showing it, for background helper runs
    if (!sites[site]) throw Error('Unknown tab');
    const view = views[site] || createView(site);
    if (state.active !== site) view.setBounds({ x: 0, y: 0, width: 1280, height: 900 });
    return view;
  }

  return { bounds, tabState, openTab, ensureView };
};
