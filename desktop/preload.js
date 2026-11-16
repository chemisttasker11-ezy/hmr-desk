const { contextBridge, ipcRenderer, webUtils } = require('electron');
function protectedDraft(op, key, value) {
  const result = ipcRenderer.sendSync('draft-store', op, key, value);
  if (!result || typeof result !== 'object' || result.error)
    throw Error(result?.error || 'Protected draft storage unavailable');
  return result.value;
}
contextBridge.exposeInMainWorld('hmr', {
  draftStore: {
    getItem: key => protectedDraft('get', key),
    setItem: (key, value) => protectedDraft('set', key, value),
    removeItem: key => protectedDraft('remove', key),
    keys: () => protectedDraft('keys'),
  },
  api: async (method, path, body) => {
    try {
      return await ipcRenderer.invoke('api', method, path, body);
    } catch (error) {
      throw new Error(error.message.replace(/^Error invoking remote method 'api': Error:\s*/, ''));
    }
  },
  signIns: (action, site, mode) => ipcRenderer.invoke('sign-ins', action, site, mode),
  onSignIn: (fn) => ipcRenderer.on('sign-in-state', (_e, r) => fn(r)),
  onEngineState: fn => ipcRenderer.on('engine-state', (_event, state) => fn(state)),
  tab: (action, site, url) => ipcRenderer.invoke('tab', action, site, url),
  openRoute: (url) => ipcRenderer.invoke('open-route', url),
  config: () => ipcRenderer.invoke('config'),
  encryptedBackup: (action, passphrase) => ipcRenderer.invoke('encrypted-backup', action, passphrase),
  migrateWorkspace: passphrase => ipcRenderer.invoke('migrate-workspace', passphrase),
  openPatientFolder: (id, file) => ipcRenderer.invoke('open-patient-folder', id, file),
  oneOff: (action, site, value) => ipcRenderer.invoke('one-off', action, site, value),
  referralPick: (kind) => ipcRenderer.invoke('referral-pick', kind),
  openReviewedReferral: token => ipcRenderer.invoke('open-reviewed-referral', token),
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
