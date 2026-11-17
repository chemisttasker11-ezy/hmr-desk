const { allowedSave, allowedFill, createGuard, createVault, publicEntry } = require('./vault');
const path = require('node:path');
module.exports = ({ ipcMain, dialog, safeStorage, dataDir, sites, views, state, getWindow, notify, canAutoSubmit }) => {
  const vault = createVault(path.join(dataDir, 'app-profile', 'sign-ins.bin'), safeStorage);
  const names = { mhr: 'My Health Record', emims: 'eMIMS', ppa: 'PPA', amh: 'AMH' };
  const guard = createGuard();
  const pages = {};
  const generations = {};
  const filled = {};
  const pending = {};
  const entries = () => vault.read();
  const senderSite = (event) =>
    Object.keys(names).find(
      (site) => !!event?.sender && !!event.senderFrame && views[site]?.webContents === event.sender && event.senderFrame === event.sender.mainFrame,
    );
  const permitted = (site, url) => allowedSave(url, sites[site].url, site);
  function update(site) {
    const v = views[site];
    if (!v) return;
    let entry;
    try {
      entry = entries()[site];
    } catch {
      entry = null;
    }
    notify('sign-in-state', {
      site,
      canSave:
        vault.available() &&
        (!entry || entry.mode === 'off') &&
        !!pages[site] &&
        permitted(site, v.webContents.getURL()),
    });
  }
  ipcMain.handle('sign-ins', async (event, action, site, mode) => {
    if (event.sender !== getWindow().webContents) throw Error('Forbidden');
    if (action === 'list') {
      if (!vault.available()) return { available: false, entries: Object.keys(names).map((s) => publicEntry(s)) };
      const data = entries();
      return { available: true, entries: Object.keys(names).map((s) => publicEntry(s, data[s])) };
    }
    if (!Object.hasOwn(names, site)) throw Error('Invalid site');
    if (action === 'request') {
      const v = views[site];
      const data = entries();
      if (
        state.active !== site ||
        !v ||
        !pages[site] ||
        (data[site] && data[site].mode !== 'off') ||
        !permitted(site, v.webContents.getURL())
      )
        throw Error('Cannot save on this page');
      pending[site] = v.webContents.getURL();
      v.webContents.send('sign-in-read');
      return;
    }
    const data = entries();
    if (action === 'mode') {
      if (!['off', 'fill', 'auto'].includes(mode) || !data[site]) throw Error('Save a sign-in first');
      data[site].mode = mode;
    } else if (action === 'forget') {
      const answer = await dialog.showMessageBox(getWindow(), {
        type: 'question',
        message: `Forget the saved sign-in for ${names[site]}?`,
        buttons: ['Forget', 'Cancel'],
        defaultId: 1,
        cancelId: 1,
      });
      if (answer.response !== 0) return;
      delete data[site];
    } else throw Error('Invalid action');
    vault.write(data);
    update(site);
  });
  ipcMain.on('sign-in-save', async (event, value) => {
    const site = senderSite(event);
    if (!site || !pending[site]) return;
    const url = event.sender.getURL();
    const requested = pending[site];
    delete pending[site];
    if (
      url !== requested ||
      !permitted(site, url) ||
      !value ||
      typeof value.username !== 'string' ||
      typeof value.password !== 'string' ||
      !value.username ||
      !value.password
    )
      return;
    const origin = new URL(url).origin;
    const answer = await dialog.showMessageBox(getWindow(), {
      type: 'question',
      message: `Save sign-in for ${names[site]}?`,
      detail: `Origin: ${origin}\nUsername: ${value.username}`,
      buttons: ['Save and fill next time', 'Save and sign in automatically', 'Cancel'],
      defaultId: 2,
      cancelId: 2,
    });
    if (answer.response === 2 || event.sender.isDestroyed() || event.sender.getURL() !== url) return;
    try {
      const data = entries();
      data[site] = {
        origin,
        username: value.username,
        password: value.password,
        mode: answer.response === 0 ? 'fill' : 'auto',
      };
      vault.write(data);
      update(site);
    } catch {
      notify('result', { site, status: 'Could not save sign-in' });
    }
  });
  ipcMain.on('sign-in-page', async (event, hasFields) => {
    const site = senderSite(event);
    if (!site) return;
    pages[site] = hasFields === true;
    update(site);
    if (!pages[site]) return;
    try {
      const data = entries();
      const entry = data[site];
      const url = event.sender.getURL();
      if (!entry || entry.mode === 'off' || !allowedFill(url, entry.origin)) return;
      if (guard.failed(site, url, generations[site])) {
        entry.mode = 'fill';
        vault.write(data);
        guard.handled(site);
        notify('result', { site, status: 'Saved sign-in did not work - check the password' });
        update(site);
        return;
      }
      if (filled[site] === generations[site]) return;
      filled[site] = generations[site];
      let submit = entry.mode === 'auto' && guard.canSubmit(site);
      const boundGeneration = generations[site], boundFrame = event.senderFrame;
      if (submit && site === 'mhr') {
        if (canAutoSubmit) {
          const allowed = await canAutoSubmit();
          if (!allowed) submit = false;
        } else {
          submit = false;
        }
      }
      if (site === 'mhr' && (views[site]?.webContents !== event.sender || event.sender.isDestroyed() || !boundFrame || boundFrame !== event.sender.mainFrame || event.sender.getURL() !== url || generations[site] !== boundGeneration || !pages[site])) return;
      if (submit) guard.submit(site, url, generations[site]);
      event.sender.send('sign-in-fill', {
        username: entry.username,
        password: entry.password,
        origin: entry.origin,
        submit,
      });
    } catch {
      notify('result', { site, status: 'Could not use saved sign-in' });
    }
  });
  return {
    update,
    requestFill(site) {
      const view = views[site];
      if (!view || !pages[site]) return;
      delete filled[site];
      view.webContents.send('sign-in-detect');
    },
    getGeneration: (site) => generations[site] || 0,
    reset(site) {
      pages[site] = false;
      generations[site] = (generations[site] || 0) + 1;
      delete pending[site];
      update(site);
    },
  };
};
