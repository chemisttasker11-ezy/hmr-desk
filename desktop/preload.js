const { contextBridge, ipcRenderer, webUtils } = require('electron');
contextBridge.exposeInMainWorld('hmr', {
  api: async (method, path, body) => {
    try {
      return await ipcRenderer.invoke('api', method, path, body);
    } catch (error) {
      throw new Error(error.message.replace(/^Error invoking remote method 'api': Error:\s*/, ''));
    }
  },
  signIns: (action, site, mode) => ipcRenderer.invoke('sign-ins', action, site, mode),
  onSignIn: (fn) => ipcRenderer.on('sign-in-state', (_e, r) => fn(r)),
  tab: (action, site, url) => ipcRenderer.invoke('tab', action, site, url),
  openRoute: (url) => ipcRenderer.invoke('open-route', url),
  config: () => ipcRenderer.invoke('config'),
  encryptedBackup: (action, passphrase) => ipcRenderer.invoke('encrypted-backup', action, passphrase),
  openPatientFolder: (id, file) => ipcRenderer.invoke('open-patient-folder', id, file),
  oneOff: (action, site, value) => ipcRenderer.invoke('one-off', action, site, value),
  referralPick: (kind) => ipcRenderer.invoke('referral-pick', kind),
  onReferralDrop: (fn) => {
    document.addEventListener('drop', async (event) => {
      if (!event.target.closest?.('#referral-drop')) return;
      event.preventDefault();
      fn({ loading: true });
      try {
        const paths = Array.from(event.dataTransfer.files, file => webUtils.getPathForFile(file));
        fn(await ipcRenderer.invoke('referral-drop', paths));
      } catch (error) { fn({ error: error.message }); }
    });
  },
  onResult: (fn) => ipcRenderer.on('result', (_e, r) => fn(r)),
  onTab: (fn) => ipcRenderer.on('tab-state', (_e, r) => fn(r)),
});
