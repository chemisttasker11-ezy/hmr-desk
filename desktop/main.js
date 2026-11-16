const { app, BrowserWindow, ipcMain, dialog, shell, safeStorage } = require('electron');
const fs = require('node:fs');
const fsp = require('node:fs/promises');
const path = require('node:path');
if (process.env.HMR_SMOKE_DATA) app.setPath('userData', path.join(process.env.HMR_SMOKE_DATA, 'electron'));
const dataDir = path.join(process.env.USERPROFILE || app.getPath('home'), 'HMR-Desk-data');
// Sign-ins live with the app's data, not under AppData: a launch from another packaged app (e.g. Claude Desktop)
// gets a private redirected AppData, which would hide the saved logins from a normal launch.
if (!process.env.HMR_SMOKE_DATA) app.setPath('userData', path.join(dataDir, 'app-profile'));
const defaults = {
  base: path.join(dataDir, 'workspace'),
  api: 'http://127.0.0.1:8767',
  tokenFile: path.join(dataDir, 'api_token'),
};
fs.mkdirSync(dataDir, { recursive: true });
const configPath = path.join(dataDir, 'app-config.json');
// Invalid historical configuration is retained under an .invalid-* copy.
// Never guess or silently reassign a patient workspace.
const loadedConfig = require('./src/config-load').loadConfig(configPath, defaults);
const isFirstRun = loadedConfig.firstRun;
// Do not save first-run configuration until the user explicitly selects it.
const config = loadedConfig.config;
let engineOwner = null;
const { start: startEngine } = require('./src/engine-owner');
const { verifyWorkspace } = require('./src/storage-choice');
const { makeVault } = require('./src/draft-vault');
const protectedDraftVault = makeVault(path.join(dataDir, 'encrypted-drafts'), safeStorage);
let recoveryRunning = false;
let engineCrashes = [];
async function restartEngineAfterCrash() {
  if (recoveryRunning || engineShutdownStarted || !app.isReady()) return;
  const now = Date.now();
  engineCrashes = engineCrashes.filter(time => now - time < 120000);
  engineCrashes.push(now);
  if (engineCrashes.length > 4) {
    win?.webContents?.send('engine-state', { ready: false, reason: 'Engine repeatedly crashed; close the app and contact support with redacted diagnostics' });
    return;
  }
  recoveryRunning = true;
  win?.webContents?.send('engine-state', { ready: false, reason: 'Clinical engine stopped; recovering local data connection' });
  try {
    for (let attempt = 0; attempt < 3; attempt++) {
      if (engineShutdownStarted) return;
      try {
        const owner = await startEngine({ resourcesPath: process.resourcesPath, dataDir,
          workspace: config.base, config, onCrash: restartEngineAfterCrash });
        if (engineShutdownStarted) { await owner.stop(); return; }
        engineOwner = owner;
        win?.webContents?.send('engine-state', { ready: true });
        return;
      } catch (error) {
        if (attempt < 2)
          await new Promise(resolve => setTimeout(resolve, 1000 + attempt * 1000));
      }
    }
    win?.webContents?.send('engine-state', { ready: false, reason: 'Clinical engine unavailable after restart attempts. Keep your protected drafts and restart the application.' });
  } finally {
    recoveryRunning = false;
  }
}
const sites = {
  mhr: {
    url: 'https://proda.humanservices.gov.au/',
    dir: 'Pathology Chrome Helper',
    key: 'HMR_PATIENTS',
    endpoint: '/api/pathology/queue',
  },
  emims: {
    url: 'https://app.emims.plus/interactions',
    dir: 'MIMS Interaction Helper',
    key: 'MIMS_LISTS',
    endpoint: '/api/mims/lists',
  },
  ppa: { url: 'https://app.ppaonline.com.au/', dir: 'PPA Claim Helper', key: 'PPA_CLAIMS', endpoint: '/api/claims' },
  sheet: { url: config.sheetUrl || 'https://docs.google.com/spreadsheets/' },
  amh: { url: 'https://amhonline.amh.net.au/' }, // sign-in and reading only; no helper script yet
};
let win;
const state = { active: null };
const results = [];
const reviewedReferrals = new (require('./src/reviewed-sources').ReviewedSources)();
const views = {},
  armed = {},
  queues = {},
  saved = {};
async function api(method, apiPath, body) {
  if (!['GET', 'POST'].includes(method) || !/^\/api\/[a-zA-Z0-9_/?=&%.-]*$/.test(apiPath))
    throw Error('Invalid API request');
  const token = process.env.HMR_TOKEN ?? (await fsp.readFile(config.tokenFile, 'utf8')).trim();
  const response = await fetch((process.env.HMR_API || config.api).replace(/\/$/, '') + apiPath, {
    method,
    headers: { 'X-HMR-Token': token, 'Content-Type': 'application/json' },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const text = await response.text();
  let json;
  try {
    json = JSON.parse(text);
  } catch {
    json = text;
  }
  if (!response.ok) {
    const message = (typeof json === 'string' ? json : json?.error) || `API error ${response.status}`;
    const e = Error(
      response.status === 404 && (apiPath.endsWith('/suggestions') || apiPath === '/api/settings')
        ? `404: ${message}`
        : message,
    );
    e.status = response.status;
    throw e;
  }
  return json;
}
function notify(channel, data) {
  if (channel === 'result') results.push(data);
  if (win && !win.isDestroyed()) win.webContents.send(channel, data);
}
const waitingTasks = {};
const { inject, saveHelper, cancel: cancelHelper } = require('./src/helpers-run')({
  getWindow: () => win,
  views,
  armed,
  queues,
  saved,
  sites,
  config,
  dataDir,
  api,
  notify,
  waitingTasks,
});
const { shape, selectQueue, fileKey } = require('./src/browser-queue');
const oneOffs = { mhr: [], emims: [] };
const chosenFolders = new Set();
let mimsStop = Promise.resolve();
let autorunInstance = null;
let prodaLogin = null;
const signIns = require('./src/sign-ins')({
  ipcMain,
  dialog,
  safeStorage,
  dataDir,
  sites,
  views,
  state,
  getWindow: () => win,
  notify,
  canAutoSubmit: () => prodaLogin?.canAutoSubmit?.() ?? false,
});
const { bounds, tabState, openTab: openBrowserTab, ensureView: ensureBrowserView } = require('./src/tabs')({
  getWindow: () => win,
  state,
  views,
  armed,
  sites,
  notify,
  inject,
  signIns,
});
async function openTab(site) {
  const result = await openBrowserTab(site);
  if (site === 'mhr') prodaLogin?.attachView(views.mhr);
  return result;
}
function ensureView(site) {
  const view = ensureBrowserView(site);
  if (site === 'mhr') prodaLogin?.attachView(view);
  return view;
}
prodaLogin = require('./src/proda-login')({
  api,
  ipcMain,
  views,
  state,
  waitingTasks,
  openTab: (s) => openTab(s),
  notify,
  signIns: () => signIns,
  autorun: () => autorunInstance,
  getWindow: () => win,
});
ipcMain.handle('api', async (e, method, p, b) => {
  if (e.sender !== win.webContents || p === '/api/referrals/review' || p.startsWith('/api/backups/') ||
      (method === 'POST' && p.endsWith('/pathology/sources')) ||
      require('./src/control').isPrivateApiRoute(p)) throw Error('Forbidden');
  return api(method, p, b);
});
ipcMain.handle('referral-pick', async (e, kind) => {
  if (e.sender !== win.webContents || !['files', 'folder', 'inbox'].includes(kind)) throw Error('Forbidden');
  const picked = kind === 'inbox' ? { canceled: false, filePaths: [path.join(config.base, 'TO SORT')] } : await dialog.showOpenDialog(win, kind === 'folder'
    ? { properties: ['openDirectory'] }
    : { properties: ['openFile', 'multiSelections'], filters: [{ name: 'PDF documents', extensions: ['pdf'] }] });
  if (picked.canceled) return null;
  let paths = picked.filePaths;
  if (kind !== 'files') paths = (await fsp.readdir(paths[0], { withFileTypes: true }))
    .filter(entry => entry.isFile() && entry.name.toLowerCase().endsWith('.pdf'))
    .map(entry => path.join(picked.filePaths[0], entry.name));
  if (!paths.length) return { rows: [{ file: 'Folder', status: 'rejected', message: 'No PDFs found in this folder.' }] };
  if (paths.length > 100) throw Error(`Folder contains ${paths.length} PDFs. Choose up to 100 files at a time.`);
  const response = await api('POST', '/api/referrals/review', { paths });
  reviewedReferrals.remember(paths, response);
  return response;
});
ipcMain.handle('referral-drop', async (e, paths) => {
  if (e.sender !== win.webContents || !Array.isArray(paths) || !paths.length || paths.length > 100 || paths.some(p => typeof p !== 'string' || !p)) throw Error('Invalid files');
  const response = await api('POST', '/api/referrals/review', { paths });
  reviewedReferrals.remember(paths, response);
  return response;
});
ipcMain.handle('open-reviewed-referral', async (e, token) => {
  if (e.sender !== win.webContents) throw Error('Forbidden');
  const verified = await reviewedReferrals.verifiedPath(token);
  const error = await shell.openPath(verified);
  if (error) throw Error('Could not open original PDF in the installed PDF viewer');
  return { opened: true };
});
ipcMain.handle('open-route', async (e, url) => {
  if (e.sender !== win.webContents) throw Error('Forbidden');
  if (!require('./src/route-url')(url)) throw Error('Invalid route URL');
  await shell.openExternal(url);
});
ipcMain.handle('config', (e) => {
  if (e.sender !== win.webContents) throw Error('Forbidden');
  return { ...config, api: process.env.HMR_API || config.api };
});
async function tabAction(action, site, url) {
  if (action === 'statuses') {
    const { pageScript } = require('./src/control');
    return Object.fromEntries(await Promise.all(['mhr', 'emims', 'ppa', 'amh'].map(async (name) => {
      const view = views[name];
      if (!view || view.webContents.isDestroyed()) return [name, 'not open'];
      if (view.webContents.isLoading()) return [name, 'loading'];
      try {
        for (const frame of view.webContents.mainFrame.framesInSubtree) await frame.executeJavaScript(pageScript('check'));
        if (name === 'mhr' && await prodaLogin.verifyClinicalReadiness(view)) return [name, 'ready'];
        return [name, 'open'];
      } catch (error) {
        return [name, /sign-in page/i.test(error.message) ? 'sign-in needed' : 'unknown'];
      }
    })));
  }
  if (action === 'hide') {
    if (state.active && views[state.active]) win.contentView.removeChildView(views[state.active]);
    state.active = null;
    return;
  }
  if (action === 'open') {
    return openTab(site);
  }
  if (action === 'load') {
    if (!Object.hasOwn(sites, site)) throw Error('Unknown tab');
    let target;
    try {
      target = new URL(url);
    } catch {
      throw Error('Invalid tab URL');
    }
    if (
      target.protocol !== 'https:' ||
      target.host !== new URL(sites[site].url).host ||
      target.username ||
      target.password
    )
      throw Error('Invalid tab URL');
    await openTab(site);
    await views[site].webContents.loadURL(target.href);
    return;
  }
  if (!views[site] || state.active !== site) throw Error('Tab not open');
  const v = views[site];
  if (action === 'back') {
    if (!v.webContents.navigationHistory.canGoBack()) return false;
    v.webContents.navigationHistory.goBack();
    return true;
  } else if (action === 'reload') v.webContents.reload();
  else if (action === 'toggle') {
    if (!sites[site].endpoint) throw Error('No action for this tab');
    if (armed[site]) {
      armed[site] = false;
      if (site === 'emims') { mimsStop = cancelHelper(site); await mimsStop; }
      tabState(site);
      return 'Stopped';
    }
    try {
      return await arm(site);
    } catch (err) {
      if (err.status === 404) return 'The engine needs updating';
      throw err;
    }
  }
}
// Fetch the site's queue, arm the helper and inject it (used by the toggle and by background auto-start).
async function arm(site) {
      if (site === 'emims') await mimsStop;
      const reply = await api('GET', sites[site].endpoint);
      const data = reply.patients || reply.lists || reply.claims || reply;
      if (!Array.isArray(data)) throw Error('Invalid engine list');
      const tasks = (await api('GET', '/api/run')).tasks;
      const selection = selectQueue(site, data, tasks);
      waitingTasks[site] = selection.waiting;
      queues[site] = [...selection.entries, ...(oneOffs[site] || [])];
      if (site !== 'ppa') {
        const names = queues[site].map((p) => fileKey(p.folder).toLowerCase());
        if (new Set(names).size !== names.length) throw Error('Duplicate names; remove or rename one-off entries');
      }
      if (!queues[site].length) return 'Nothing to run';
      armed[site] = true;
      tabState(site);
      try { await inject(site); }
      catch (error) { armed[site] = false; tabState(site); throw error; }
      return 'Ready';
}
ipcMain.handle('tab', async (e, action, site, url) => {
  if (e.sender !== win.webContents) throw Error('Forbidden');
  return tabAction(action, site, url);
});
ipcMain.handle('one-off', async (e, action, site, value) => {
  if (e.sender !== win.webContents || !oneOffs[site]) throw Error('Forbidden');
  if (action === 'pick') {
    const result = await dialog.showOpenDialog(win, { properties: ['openDirectory'] });
    if (result.canceled) return '';
    chosenFolders.add(result.filePaths[0]);
    return result.filePaths[0];
  }
  if (action === 'list') return oneOffs[site].map((p) => p.folder);
  if (action === 'remove') {
    if (armed[site]) throw Error('Stop the helper before removing an entry');
    oneOffs[site].splice(Number(value), 1);
  } else if (action === 'add') {
    if (armed[site]) throw Error('Stop the helper before adding an entry');
    if (!chosenFolders.has(value.folder_path)) throw Error('Choose a folder');
    const entry = shape(site, value, value.folder_path);
    if (oneOffs[site].some((p) => fileKey(p.folder).toLowerCase() === fileKey(entry.folder).toLowerCase())) {
      throw Error('That name is already in the one-off list');
    }
    oneOffs[site].push(entry);
  }
  return oneOffs[site].map((p) => p.folder);
});
ipcMain.handle('pathology-source-pick', async (e, patientId) => {
  if (e.sender !== win.webContents || !Number.isSafeInteger(patientId) || patientId < 1)
    throw Error('Invalid patient');
  const picked = await dialog.showOpenDialog(win, {
    title: 'Select a pathology PDF to import as an unconfirmed source',
    properties: ['openFile'], filters: [{name:'PDF documents',extensions:['pdf']}],
  });
  if (picked.canceled || !picked.filePaths[0]) return {cancelled:true};
  return api('POST', `/api/patients/${patientId}/pathology/sources`,
    {path:picked.filePaths[0]});
});
ipcMain.handle('open-pathology-source', async (e, patientId, sourceId) => {
  if (e.sender !== win.webContents || !Number.isSafeInteger(patientId) || patientId < 1 ||
      typeof sourceId !== 'string' || !/^[a-f0-9]{32}$/.test(sourceId)) throw Error('Invalid source');
  const sourceIndex = await api('GET', `/api/patients/${patientId}/pathology/sources`);
  const source = sourceIndex.sources?.find(item => item.id === sourceId);
  if (!source || !/^[a-f0-9]{64}$/.test(source.sha256 || '') ||
      path.basename(source.name) !== source.name || !source.name.toLowerCase().endsWith('.pdf'))
    throw Error('Source not found');
  const patient = await api('GET', `/api/patients/${patientId}`);
  const base = await fsp.realpath(config.base);
  const folder = await fsp.realpath(path.resolve(base, patient.folder_path || patient.folder));
  if (!require('./src/folder').inside(base, folder)) throw Error('Patient folder outside workspace');
  const pathology = await fsp.realpath(path.join(folder,'Pathology'));
  if (path.dirname(pathology) !== folder) throw Error('Invalid pathology folder');
  const target = await fsp.realpath(path.join(pathology, source.name));
  if (path.dirname(target) !== pathology || !(await fsp.stat(target)).isFile())
    throw Error('Untrusted pathology source path');
  const crypto = require('node:crypto');
  const hash = crypto.createHash('sha256').update(await fsp.readFile(target)).digest('hex');
  if (hash !== source.sha256) throw Error('Original source changed since import');
  const failure = await shell.openPath(target);
  if (failure) throw Error('Windows could not open the source PDF viewer');
  return {opened:true};
});
ipcMain.handle('open-report-version', async (e, patientId, reportFile, format) => {
  if (e.sender !== win.webContents || !Number.isSafeInteger(patientId) || patientId < 1 ||
      typeof reportFile !== 'string' || path.basename(reportFile) !== reportFile ||
      !reportFile.toLowerCase().endsWith('.docx') ||
      ['<', '>', ':', '"', '/', String.fromCharCode(92), '|', '?', '*'].some(ch => reportFile.includes(ch)) ||
      !['docx', 'pdf'].includes(format))
    throw Error('Invalid report preview request');
  const versions = await api('GET', `/api/patients/${patientId}/report-versions`);
  const version = versions.versions?.find(row => row.file === reportFile && row.document_matches_build &&
    (format === 'docx' || row.pdf_exists_and_matches));
  if (!version) throw Error('Report version is not a verified HMR Desk output');
  const patient = await api('GET', `/api/patients/${patientId}`);
  const base = await fsp.realpath(config.base);
  const patientFolder = await fsp.realpath(path.resolve(base, patient.folder_path || patient.folder));
  if (!require('./src/folder').inside(base, patientFolder)) throw Error('Patient path outside workspace');
  const name = format === 'pdf' ? reportFile.replace(/\.docx$/i, '.pdf') : reportFile;
  const selected = await fsp.realpath(path.join(patientFolder, name));
  if (path.dirname(selected) !== patientFolder || !(await fsp.stat(selected)).isFile())
    throw Error('Report file is not inside this patient folder');
  const openError = await shell.openPath(selected);
  if (openError) throw Error('Windows could not open this file; use an installed compatible viewer');
  return {opened:true};
});
ipcMain.handle('open-patient-folder', async (e, id, file) => {
  if (e.sender !== win.webContents || !Number.isSafeInteger(id) || id < 1) throw Error('Forbidden');
  const patient = await api('GET', `/api/patients/${id}`);
  const folder = patient.folder_path || patient.folder;
  if (typeof folder !== 'string' || !folder) throw Error('Patient has no folder');
  const base = await fsp.realpath(config.base);
  const target = await fsp.realpath(path.resolve(base, folder));
  if (!require('./src/folder').inside(base, target)) {
    throw Error('Patient folder is outside the configured base');
  }
  if (!(await fsp.stat(target)).isDirectory()) throw Error('Patient folder is not a directory');
  let openTarget = target;
  if (file !== undefined) {
    if (typeof file !== 'string' || path.basename(file) !== file || !(/^mims interactions.*\.txt$/i.test(file) || /^PPA Consent - .+ signed\.pdf$/i.test(file)))
      throw Error('Invalid interaction file');
    openTarget = await fsp.realpath(path.join(target, file));
    if (
      !require('./src/folder').inside(target, openTarget) ||
      !require('./src/folder').inside(base, openTarget) ||
      !(await fsp.stat(openTarget)).isFile()
    )
      throw Error('Invalid interaction file');
  }
  const error = await shell.openPath(openTarget);
  if (error) throw Error(error);
});
ipcMain.on('draft-store', (e, action, key, value) => {
  if (e.sender !== win?.webContents) {
    e.returnValue = { error: 'Unauthorised draft request' };
    return;
  }
  try {
    const permitted = { get: 'getItem', set: 'setItem', remove: 'removeItem', keys: 'keys' };
    if (!Object.hasOwn(permitted, action)) throw Error('Invalid protected draft operation');
    e.returnValue = { value: protectedDraftVault[permitted[action]](key, value) ?? null };
  } catch (error) {
    e.returnValue = { error: 'Protected draft storage failed (' + error.constructor.name + ')' };
  }
});
ipcMain.handle('encrypted-backup', async (e, action, passphrase) => {
  if (e.sender !== win.webContents || !['create', 'restore', 'preview'].includes(action) ||
      typeof passphrase !== 'string' || passphrase.length < 12 || passphrase.length > 512)
    throw Error('Invalid backup request or passphrase (minimum 12 characters)');
  if (action === 'create') {
    const chosen = await dialog.showSaveDialog(win, { title: 'Save encrypted HMR backup',
      defaultPath: path.join(app.getPath('documents'), 'hmr-backup.hmrbak'),
      filters: [{ name: 'Encrypted HMR backup', extensions: ['hmrbak'] }] });
    if (chosen.canceled || !chosen.filePath) return { cancelled: true };
    return api('POST', '/api/backups/create', { target: chosen.filePath, passphrase });
  }
  const chosen = await dialog.showOpenDialog(win, { title: 'Choose encrypted HMR backup',
    properties: ['openFile'], filters: [{ name: 'Encrypted HMR backup', extensions: ['hmrbak'] }] });
  if (chosen.canceled || !chosen.filePaths.length) return { cancelled: true };
  const inspection = await api('POST', '/api/backups/preview',
    { source: chosen.filePaths[0], passphrase });
  if (action === 'preview') return inspection;
  const confirmation = await dialog.showMessageBox(win, {
    type: 'question',
    title: 'Verified isolated restore',
    message: 'Verified encrypted backup: ' + inspection.patients + ' patient records and ' +
      inspection.workspace_files + ' patient workspace files.',
    detail: 'Restore will create a separate, new folder. Your current database and workspace will NOT be replaced. Continue?',
    buttons: ['Continue isolated restore', 'Cancel'], defaultId: 1, cancelId: 1, noLink: true,
  });
  if (confirmation.response !== 0) return { cancelled: true };
  const folder = await dialog.showOpenDialog(win, { title: 'Choose parent folder for isolated restore',
    properties: ['openDirectory', 'createDirectory'] });
  if (folder.canceled || !folder.filePaths.length) return { cancelled: true };
  const dest = path.join(folder.filePaths[0], 'HMR-Restored-' + Date.now());
  return api('POST', '/api/backups/restore',
    { source: chosen.filePaths[0], destination: dest, passphrase });
});
ipcMain.handle('activate-restored', async (e, passphrase) => {
  if (e.sender !== win.webContents || typeof passphrase !== 'string' ||
      passphrase.length < 12 || passphrase.length > 512 || !engineOwner || engineShutdownStarted)
    throw Error('Invalid recovery activation request');
  const chosen = await dialog.showOpenDialog(win, {
    title: 'Choose an isolated restored dataset containing data and workspace folders',
    properties: ['openDirectory'],
  });
  if (chosen.canceled || !chosen.filePaths.length) return {cancelled:true};
  const recovery = require('./src/restore-activation');
  const inventory = await recovery.verifyRestored(chosen.filePaths[0]);
  const backup = await dialog.showSaveDialog(win, {
    title: 'Mandatory encrypted backup of CURRENT data before activating recovered cases',
    defaultPath: path.join(app.getPath('documents'),'hmr-before-restore-activation.hmrbak'),
    filters:[{name:'Encrypted HMR backup',extensions:['hmrbak']}],
  });
  if (backup.canceled || !backup.filePath) return {cancelled:true};
  const confirmation = await dialog.showMessageBox(win, {
    type:'warning',title:'Activate restored HMR dataset',
    message:'Replace active patient database with ' + inventory.files +
      ' verified files (' + inventory.bytes + ' bytes)?',
    detail:'First, HMR Desk encrypts a complete CURRENT backup. It then stops the engine, preserves the old SQLite database and old workspace for rollback, installs the verified recovered data and restarts. No existing patient files are deleted.',
    buttons:['Back up and activate', 'Cancel'], defaultId:1,cancelId:1,noLink:true,
  });
  if (confirmation.response !== 0) return {cancelled:true};
  await api('POST','/api/backups/create',{target:backup.filePath,passphrase});
  engineShutdownStarted=true;
  try {
    await engineOwner.stop();
    engineOwner=null;
    const outcome=await recovery.activateRestored(chosen.filePaths[0],dataDir,configPath);
    config.base=outcome.workspace;
    app.relaunch();
    app.quit();
    return {restarting:true,previousDataPreserved:true};
  } catch(error) {
    engineShutdownStarted=false;
    if (!engineOwner) {
      try {
        const disk=JSON.parse(await fsp.readFile(configPath,'utf8'));
        config.base=disk.base;
        engineOwner=await startEngine({resourcesPath:process.resourcesPath,dataDir,
          workspace:config.base,config,onCrash:restartEngineAfterCrash});
      } catch {
        win?.webContents?.send('engine-state',{ready:false,reason:
          'Recovery activation did not complete. The prior database and workspace have been preserved. Restart HMR Desk.'});
      }
    }
    throw error;
  }
});
ipcMain.handle('migrate-workspace', async (e, passphrase) => {
  if (e.sender !== win.webContents || typeof passphrase !== 'string' ||
      passphrase.length < 12 || passphrase.length > 512 || !engineOwner)
    throw Error('Invalid workspace migration request');
  const chosen = await dialog.showOpenDialog(win, {
    title: 'Choose destination parent for a new patient workspace',
    properties: ['openDirectory', 'createDirectory'],
  });
  if (chosen.canceled || !chosen.filePaths.length) return {cancelled:true};
  const target = path.join(chosen.filePaths[0], 'HMR-Desk-Workspace-Migrated');
  const backup = await dialog.showSaveDialog(win, {
    title: 'Choose a separate location for the mandatory encrypted pre-migration backup',
    defaultPath: path.join(app.getPath('documents'), 'hmr-before-migration.hmrbak'),
    filters: [{name:'Encrypted HMR backup',extensions:['hmrbak']}],
  });
  if (backup.canceled || !backup.filePath) return {cancelled:true};
  const { inventory, prepareMigration } = require('./src/workspace-migration');
  const scanned = await inventory(config.base);
  if (!scanned.entries.length) throw Error('Current workspace has no files to migrate');
  const confirmation = await dialog.showMessageBox(win, {
    type: 'question',
    title: 'Preserve patient data and migrate workspace',
    message: 'Copy ' + scanned.entries.length + ' files (' + scanned.bytes + ' bytes) into a new local workspace?',
    detail: 'HMR Desk will first create an encrypted recovery backup, close the clinical engine, copy and hash-check every file, then restart with the new folder. The original remains untouched.',
    buttons: ['Back up and migrate', 'Cancel'], defaultId:1, cancelId:1, noLink:true,
  });
  if (confirmation.response !== 0) return {cancelled:true};
  await api('POST', '/api/backups/create', {target:backup.filePath,passphrase});
  engineShutdownStarted = true;
  try {
    await engineOwner.stop();
    engineOwner = null;
    await prepareMigration(config.base, target);
    const nextConfig = {...config, base:target};
    const temporaryConfig = configPath + '.migrating-' + process.pid;
    try {
      await fsp.writeFile(temporaryConfig, JSON.stringify(nextConfig, null, 2), {mode:0o600,flag:'wx'});
      await fsp.rename(temporaryConfig, configPath);
    } finally {
      await fsp.rm(temporaryConfig,{force:true});
    }
    config.base = target;
    app.relaunch();
    app.quit();
    return {restarting:true, destination:target};
  } catch (error) {
    engineShutdownStarted = false;
    if (!engineOwner) {
      try {
        engineOwner = await startEngine({resourcesPath:process.resourcesPath,dataDir,
          workspace:config.base,config,onCrash:restartEngineAfterCrash});
      } catch {
        win?.webContents?.send('engine-state',{ready:false,
          reason:'Workspace migration interrupted; original patient files remain intact. Restart the application.'});
      }
    }
    throw error;
  }
});
ipcMain.handle('save-helper', saveHelper);
const hasLock = app.requestSingleInstanceLock();
if (!hasLock) app.quit();
app.on('second-instance', () => {
  if (win) {
    if (win.isMinimized()) win.restore();
    win.focus();
  }
});
if (hasLock)
  app.whenReady().then(async () => {
    // Recover interrupted SQLite/config activation before any engine opens data.
    if (await require('./src/restore-activation').recoverInterruptedRestore(dataDir,configPath)) {
      Object.assign(config, JSON.parse(await fsp.readFile(configPath,'utf8')));
    }
    if (isFirstRun && app.isPackaged && !process.env.HMR_SMOKE_DATA && !process.env.HMR_API) {
      const choice = await dialog.showMessageBox({
        type: 'question', title: 'HMR Desk — first-run storage',
        message: 'Choose where HMR patient files are kept',
        detail: (loadedConfig.recovery ? loadedConfig.recovery + '\\n\\n' : '') +
          'The recommended folder is on this Windows account. You may select a different writable local folder. Existing patient data is never imported or moved without a separate confirmed migration.',
        buttons: ['Use recommended folder', 'Choose a different folder', 'Exit'],
        defaultId: 0, cancelId: 2, noLink: true,
      });
      if (choice.response === 2) { app.quit(); return; }
      if (choice.response === 1) {
        const picked = await dialog.showOpenDialog({
          title: 'Select patient workspace', properties: ['openDirectory', 'createDirectory'],
          defaultPath: app.getPath('documents'),
        });
        if (picked.canceled || !picked.filePaths[0]) { app.quit(); return; }
        config.base = picked.filePaths[0];
      }
      try {
        config.base = verifyWorkspace(config.base);
        fs.writeFileSync(configPath, JSON.stringify(config, null, 2), { mode: 0o600 });
      } catch (error) {
        dialog.showErrorBox('Patient workspace unavailable', String(error.message).slice(0, 250));
        app.quit();
        return;
      }
    }
    if (app.isPackaged && !process.env.HMR_API && !process.env.HMR_SMOKE_URL && !process.env.HMR_SHOTS) {
      try {
        engineOwner = await startEngine({ resourcesPath: process.resourcesPath, dataDir, workspace: config.base, config, onCrash: restartEngineAfterCrash });
      } catch (error) {
        dialog.showErrorBox('HMR Desk engine unavailable', error.message);
        app.quit();
        return;
      }
    }
    win = new BrowserWindow({
      width: 1440,
      height: 900,
      minWidth: 1280,
      minHeight: 720,
      webPreferences: {
        preload: path.join(__dirname, 'preload.js'),
        contextIsolation: true,
        nodeIntegration: false,
        sandbox: true,
      },
    });
    win.loadFile('index.html');
    // the app window never navigates away; tel: links (phone numbers) go to Windows
    win.webContents.on('will-navigate', (event, url) => {
      event.preventDefault();
      if (/^tel:(\+|%2B)?(\d|%20| ){6,40}$/i.test(url)) shell.openExternal(url);
    });
    win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
    require('./src/control').start({
      getWindow: () => win,
      state,
      views,
      armed,
      oneOffs,
      results,
      saved,
      tabAction,
      dataDir,
      authStatus: (b) => prodaLogin?.authStatus(b),
      prodaLogin: (b) => prodaLogin?.triggerLogin(b),
    });
    if (!process.env.HMR_SMOKE_URL && !process.env.HMR_SHOTS) {
      autorunInstance = require('./src/autorun')({
        api, armed, waitingTasks, ensureView, arm, notify, pageScript: require('./src/control').pageScript,
      });
      autorunInstance.start();
    }
    if (process.env.HMR_SHOTS) win.webContents.once('did-finish-load', () => captureShots());
    if (process.env.HMR_SMOKE_URL)
      win.webContents.once('did-finish-load', async () => {
        try {
          await openTab('mhr');
          const reply = await api('GET', '/api/pathology/queue');
          queues.mhr = reply.patients || reply;
          armed.mhr = true;
          const v = views.mhr;
          if (v.webContents.isLoading()) await new Promise((ok) => v.webContents.once('did-finish-load', ok));
          const refused = await win.webContents.executeJavaScript(
            "window.hmr.signIns('request', 'mhr').then(() => false, () => true)",
          );
          if (!refused) throw Error('HTTP sign-in fixture was not refused');
          await v.webContents.executeJavaScript("document.querySelector('form').remove()");
          await inject('mhr');
          await v.webContents.executeJavaScript("document.getElementById('hmr-save-pdf').click()");
        } catch (e) {
          console.error(e.message);
          app.exit(1);
        }
      });
    win.on('resize', bounds);
    win.on('closed', () => {
      win = null;
    });
  });
let engineShutdownStarted = false;
app.on('before-quit', event => {
  if (!engineOwner || engineShutdownStarted) return;
  event.preventDefault();
  engineShutdownStarted = true;
  engineOwner.stop().finally(() => app.quit());
});
app.on('window-all-closed', () => app.quit());

async function captureShots() {
  const output = path.join(__dirname, 'shots');
  await fsp.mkdir(output, { recursive: true });
  let phase = 'startup';
  const originalAmhUrl = sites.amh.url;
  let syntheticSignInListeners, originalSignInUpdate, originalSignInReset;
  const rendererErrors = [];
  const onConsole = (_event, levelOrDetails, message) => {
    const level = typeof levelOrDetails === 'object' ? levelOrDetails.level : levelOrDetails;
    const text = typeof levelOrDetails === 'object' ? levelOrDetails.message : message;
    if ((level === 'error' || level === 3) && text) { rendererErrors.push(String(text).slice(0, 1000)); if (rendererErrors.length > 10) rendererErrors.shift(); }
  };
  win.webContents.on('console-message', onConsole);
  const shot = async (name) => {
    phase = 'capture ' + name;
    await new Promise((resolve) => setTimeout(resolve, 300));
    await fsp.writeFile(path.join(output, name + '.png'), (await win.webContents.capturePage()).toPNG());
  };
  const run = async (code, label) => {
    if (label) phase = label;
    const result = await win.webContents.executeJavaScript(`(async () => { try { return { ok: true, value: await (${code}) }; } catch (e) { return { ok: false, error: String(e && (e.stack || e.message) || e) }; } })()`);
    if (!result?.ok) throw Error(`${phase}: ${result?.error || 'renderer script failed'}`);
    return result.value;
  };
  try {
    if (process.env.HMR_API !== 'http://127.0.0.1:18765' || !process.env.HMR_SMOKE_DATA) throw Error('Screenshot capture requires the isolated mock environment');
    win.setSize(1440, 900);
    if (!process.env.HMR_SHOT_FLOW_ONLY) {
    for (const page of ['today', 'messages', 'calendar', 'run', 'patients', 'interview', 'reports', 'settings', 'intake', 'sheet', 'claim', 'followup', 'to_book', 'activity']) {
      phase = 'navigate ' + page;
      await win.webContents.executeJavaScript(`navigate(${JSON.stringify(page)})`);
      const heading = {
        today: 'Today', messages: 'Book',
        calendar: 'Visit',
        run: 'Activity',
        patients: 'Patients',
        interview: 'Visit',
        reports: 'Report',
        settings: 'Settings',
        intake: 'Book',
        claim: 'Claim', followup: 'Follow-up', to_book: 'Book', activity: 'Activity',
        sheet: 'Sheet',
      }[page];
      const deadline = Date.now() + 15000;
      while (Date.now() < deadline) {
        const ready = await win.webContents.executeJavaScript(
          `document.querySelector('#title')?.textContent === ${JSON.stringify(heading)} && (${JSON.stringify(page)} === 'sheet' || (document.querySelector('#screen')?.dataset.loadedPage === ${JSON.stringify(page === 'activity' ? 'run' : page)} && (${JSON.stringify(page)} !== 'settings' || !!document.querySelector('#saved-sign-ins'))))`,
        );
        if (ready) break;
        await new Promise((resolve) => setTimeout(resolve, 100));
      }
      if (Date.now() >= deadline) throw Error(`Screen did not load: ${page}`);
      await new Promise((resolve) => setTimeout(resolve, 900)); // let late renders settle before the capture
      if (page === 'patients') {
        await win.webContents.executeJavaScript(`
          for (let index = 0; index < 2; index++) {
            const box = document.querySelectorAll('[data-select-patient]')[index];
            if (box && !box.checked) box.click();
          }`);
        await new Promise((resolve) => setTimeout(resolve, 700));
      }
      const image = await win.webContents.capturePage();
      await fsp.writeFile(path.join(output, (page === 'to_book' ? 'book' : page) + '.png'), image.toPNG());
      if (page === 'patients') {
        for (const stage of ['booking', 'ready', 'report']) {
          await win.webContents.executeJavaScript(`showPatient(patients.find(p => p.stage === '${stage}').id)`);
          await new Promise((resolve) => setTimeout(resolve, 700));
          await fsp.writeFile(path.join(output, `patients-open-${stage}.png`), (await win.webContents.capturePage()).toPNG());
        }
      }
      if (page === 'patients') {
        await run(`(() => {
          const sort = document.querySelector('#patient-sort'), range = document.querySelector('#appointment-range');
          if (!sort || !range) throw Error('Patient sort or appointment range missing');
          window.__shotPatientFilters = [sort.value, range.value];
          sort.value = 'appointment'; sort.dispatchEvent(new Event('change', { bubbles: true }));
          const updatedRange = document.querySelector('#appointment-range'); updatedRange.value = 'week'; updatedRange.dispatchEvent(new Event('change', { bubbles: true }));
          if (document.querySelector('#patient-sort').value !== 'appointment' || document.querySelector('#appointment-range').value !== 'week') throw Error('Patient sort or appointment range not retained');
        })()`);
        await shot('patients-appointment-sort-week-1440');
        await run(`(() => {
          const sort = document.querySelector('#patient-sort'); sort.value = window.__shotPatientFilters[0]; sort.dispatchEvent(new Event('change', { bubbles: true }));
          const range = document.querySelector('#appointment-range'); range.value = window.__shotPatientFilters[1]; range.dispatchEvent(new Event('change', { bubbles: true }));
        })()`);
      }
      if (page === 'patients') {
        await run(`(async () => {
          const before = JSON.stringify([...checkedPatients].sort());
          const result = await openPatientWorkspace(1, 'Overview', 'split');
          if (!result.ok || selected !== '1') throw Error('Synthetic patient did not open');
          window.__shotChecked = before;
          const divider = document.querySelector('#patient-divider');
          divider.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
          if (divider.getAttribute('aria-valuenow') !== '55') throw Error('Split resize failed');
        })()`);
        await shot('patient-split-resized-1440');
        for (const mode of ['list', 'patient', 'split']) {
          await run(`(async () => {
            const button = [...document.querySelectorAll('[data-patient-layout="${mode}"]')].find(el => !el.hidden && el.getClientRects().length);
            if (!button) throw Error('Missing layout control: ${mode}');
            button.click();
            for (let n = 0; n < 50 && patientLayout !== '${mode}'; n++) await new Promise(resolve => setTimeout(resolve, 100));
            if (patientLayout !== '${mode}' || selected !== '1' || JSON.stringify([...checkedPatients].sort()) !== window.__shotChecked) throw Error('Patient state was not preserved: ${mode}');
          })()`, `patient layout ${mode}`);
          await shot(`patient-${mode === 'split' ? 'split-restored' : mode + '-max'}-1440`);
        }
        for (const tab of ['Conversation', 'Activity', 'Files']) {
          await run(`(async () => {
            document.querySelector('#detail [data-tab="${tab}"]').click();
            for (let n = 0; n < 50 && detailTab !== '${tab}'; n++) await new Promise(resolve => setTimeout(resolve, 100));
            if (detailTab !== '${tab}' || document.querySelector('#detail .${tab.toLowerCase()}-view').hidden || JSON.stringify([...checkedPatients].sort()) !== window.__shotChecked) throw Error('Patient tab state not preserved: ${tab}');
          })()`, `patient tab ${tab}`);
          await shot(`patient-${tab.toLowerCase()}-1440`);
        }
      }
      if (page === 'settings') {
        for (const [selector, filename] of [
          ['#practice-settings', 'settings-practice.png'],
          ['#saved-sign-ins', 'settings-sign-ins.png'],
        ]) {
          await win.webContents.executeJavaScript(`document.querySelector('${selector}')?.scrollIntoView()`);
          await new Promise((resolve) => setTimeout(resolve, 300));
          await fsp.writeFile(path.join(output, filename), (await win.webContents.capturePage()).toPNG());
        }
      }
      if (page === 'interview') {
        phase = 'interview synthetic editing and save';
        await run(`(async () => {
          if (interviewId !== '1') await switchInterview('1');
          if (!interviewRecord || interviewId !== '1') throw Error('Synthetic interview unavailable');
          const click = selector => { const el = document.querySelector(selector); if (!el) throw Error('Missing interview control: ' + selector); el.click(); };
          const input = (selector, value) => { const el = document.querySelector(selector); if (!el) throw Error('Missing interview input: ' + selector); el.value = value; el.dispatchEvent(new Event('input', { bubbles: true })); };
          click('[data-detail="manager"][value="other"]'); input('[data-detail="manager_details"]', 'Synthetic caregiver');
          click('[data-detail="daa"][value="yes"]'); click('[data-detail="daa_type"][value="webster"]');
          input('[data-detail="daa_pharmacy"]', 'Synthetic pharmacy');
          click('[data-detail="smoking"][value="ex"]'); click('[data-detail="alcohol"][value="yes"]'); input('[data-detail="alcohol_details"]', 'Synthetic detail');
          input('[data-usage-preset][data-row="0"]', '1m');
          click('[data-med-detail="checked"][data-row="0"]');
          click('[data-use-field="use_status"][data-use-table="meds"][data-row="1"][value="not_using"]');
          input('[data-use-field="use_reason"][data-use-table="meds"][data-row="1"]', 'stopped_gp');
          click('[data-other-checked][data-row="0"]');
          if (!await saveInterview(true)) throw Error('Synthetic interview save failed');
          const saved = await hmr.api('GET', '/api/patients/1/interview');
          if (saved.meds[0][2] !== '1 in the morning' || !saved.details.meds[0].checked || saved.details.meds[1].use_status !== 'not_using' || !saved.details.other_meds[0].checked || saved.details.manager !== 'other' || saved.details.daa_type !== 'webster') throw Error('Synthetic interview changes did not persist');
          if (!document.querySelector('[data-interview-save]') || document.querySelectorAll('#section-meds, #section-other_meds, #section-not_using_meds').length !== 3) throw Error('Interview controls missing');
        })()`);
        for (const [section, name] of [['manages_meds', 'interview-caregiver-daa-1440'], ['alcohol_smoking', 'interview-smoking-alcohol-1440'], ['meds', 'interview-referral-medicines-1440'], ['other_meds', 'interview-found-medicines-1440'], ['not_using_meds', 'interview-stopped-medicines-1440']]) {
          await run(`document.querySelector('#section-${section}').scrollIntoView()`);
          await shot(name);
        }
        await win.webContents.executeJavaScript(
          `document.querySelector('[data-prop="by"][value="authorised"]')?.click(); document.querySelector('#section-consent')?.scrollIntoView();`,
        );
        await new Promise((resolve) => setTimeout(resolve, 700));
        const consent = await win.webContents.capturePage();
        await fsp.writeFile(path.join(output, 'interview-consent.png'), consent.toPNG());
        if (!await run('saveInterview(true)')) throw Error('Synthetic consent draft did not save');
      }
      if (page === 'intake') {
        phase = 'referral synthetic review setup';
        await run(`(async () => {
          const result = await hmr.api('GET', '/api/shots/referrals');
          referralRows = result.rows; renderReferrals();
          if (referralRows.length !== 4 || !document.querySelector('[data-referral-commit="0"]') || !document.querySelector('[data-referral-commit="1"]')) throw Error('Synthetic referral review missing');
        })()`);
        for (const [index, name] of [[0, 'referral-review-1440'], [1, 'referral-duplicate-1440'], [2, 'referral-error-1440']]) {
          await run(`document.querySelectorAll('#referral-results article')[${index}].scrollIntoView()`);
          await shot(name);
        }
        phase = 'referral validation error';
        await run(`(async () => {
          const form = document.querySelector('[data-referral-commit="0"]');
          form.scrollIntoView(); form.requestSubmit();
          for (let n = 0; n < 50 && !form.querySelector('.error').textContent; n++) await new Promise(resolve => setTimeout(resolve, 100));
          if (!form.querySelector('.error').textContent.includes('Synthetic review error') || referralRows[0].status !== 'review') throw Error('Referral error did not preserve the review row');
        })()`);
        await shot('referral-validation-error-1440');
      }
      if (page === 'reports') {
        await win.webContents.executeJavaScript(`document.querySelector('[data-report-open]')?.click()`);
        await new Promise((resolve) => setTimeout(resolve, 700));
        await win.webContents.executeJavaScript(
          `const search = document.querySelector('#library-search'); if (search) { search.value = 'example'; search.dispatchEvent(new Event('input', { bubbles: true })); }`,
        );
        await new Promise((resolve) => setTimeout(resolve, 700));
        await run(`(() => { if (!document.querySelector('[data-report-refresh]') || !document.querySelector('#report-details')?.open) throw Error('Stale report state missing'); })()`);
        await shot('report-editor-stale-1440');
        const editor = await win.webContents.capturePage();
        await fsp.writeFile(path.join(output, 'report-editor.png'), editor.toPNG());
        await win.webContents.executeJavaScript(`navigate('reports')`);
        await new Promise((resolve) => setTimeout(resolve, 700));
      }
      if (page === 'patients' || page === 'reports') {
        const selector = page === 'patients' ? '[data-patient]' : '[data-medicines]';
        await win.webContents.executeJavaScript(`document.querySelector('${selector}')?.click()`);
        await new Promise((resolve) => setTimeout(resolve, 700));
        const detail = await win.webContents.capturePage();
        await fsp.writeFile(path.join(output, page + '-open.png'), detail.toPNG());
        if (page === 'reports') await run(`medicinePatient ? reportClick({ dataset: { closeMedicines: '' } }) : null`);
      }
    }
    win.setSize(1280, 720);
    await run(`(async () => {
      await navigate('patients');
      const result = await openPatientWorkspace(1, 'Conversation', 'split');
      if (!result.ok || selected !== '1' || JSON.stringify([...checkedPatients].sort()) !== window.__shotChecked) throw Error('Compact patient state not preserved');
    })()`);
    await shot('patient-conversation-split-1280');
    }
    win.setSize(1280, 720);
    await run(`(async () => {
      await navigate('interview');
      if (interviewId !== '1') await switchInterview('1');
      if (!interviewRecord) throw Error('Synthetic interview unavailable');
      document.querySelector('#section-meds').scrollIntoView();
    })()`);
    await shot('interview-referral-medicines-1280');
    await shot('interview-sticky-1280');
    await run(`(() => { document.querySelector('#section-meds [data-interview-details]')?.click(); document.querySelector('#section-meds').scrollIntoView(); })()`);
    await shot('interview-medicines-compact-1280');
    await run(`(() => { document.querySelector('#section-health_check').scrollIntoView(); })()`);
    await shot('interview-health-check-1280');
    await run(`(() => { document.querySelector('#section-social').scrollIntoView(); })()`);
    await shot('interview-visit-living-1280');
    phase = 'synthetic interview preset and movement';
    await run(`(async () => {
      window.__flowOriginalMeds = JSON.parse(JSON.stringify(interviewRecord.meds));
      window.__flowOriginalMeta = JSON.parse(JSON.stringify(interviewRecord.details.meds));
      interviewRecord.meds = []; interviewRecord.details.meds = [];
      for (let n = 0; n < 4; n++) {
        interviewRecord.meds.push(['Synthetic medicine ' + n, 'Daily', '', '', '']);
        interviewRecord.details.meds.push({ checked: false, priority: 0, as_instructed: false });
      }
      normalizeInterviewDetails(interviewRecord); renderInterview();
      window.__flowFirst = interviewRecord.meds.length - 4;
      const actual = document.querySelector('[data-field="meds"][data-row="' + window.__flowFirst + '"][data-col="2"]');
      actual.scrollIntoView({ block: 'center' }); actual.focus(); actual.value = '1'; actual.setSelectionRange(1, 1);
      actual.dispatchEvent(new Event('input', { bubbles: true }));
      const select = actual.closest('.interview-actual').querySelector('[data-usage-preset]');
      if (document.activeElement !== actual || actual.value !== '1' || actual.selectionStart !== 1 || actual.selectionEnd !== 1 || !select.options[0].text.includes('matching presets') || ![...select.options].some(o => o.value === '1m') || [...select.options].some(o => o.value === '2bd')) throw Error('Preset matching changed text, caret or options');
    })()`);
    await shot('interview-preset-matches-1280');
    await run(`(() => {
      const i = window.__flowFirst, select = document.querySelector('[data-usage-preset="meds"][data-row="' + i + '"]');
      select.value = '1m'; select.dispatchEvent(new Event('input', { bubbles: true }));
      if (interviewRecord.meds[i][2] !== '1 in the morning') throw Error('Preset did not apply readable directions');
      document.querySelector('[data-med-detail="checked"][data-row="' + i + '"]').click();
      const active = document.activeElement, rect = active.getBoundingClientRect();
      const headerBottom = Math.max(document.querySelector('main > header').getBoundingClientRect().bottom, document.querySelector('.interview-context').getBoundingClientRect().bottom);
      if (active.dataset.field !== 'meds' || active.dataset.row !== String(i + 1) || active.dataset.col !== '2' || rect.top < headerBottom - 1 || rect.bottom > innerHeight + 1) { const expected = document.querySelector('[data-field="meds"][data-row="' + (i + 1) + '"][data-col="2"]'); throw Error('Checked focus diagnostic: ' + JSON.stringify({ active: { ...active.dataset }, expectedRow: i + 1, activeRect: { top: rect.top, bottom: rect.bottom }, targetPresent: !!expected, targetRect: expected ? { top: expected.getBoundingClientRect().top, bottom: expected.getBoundingClientRect().bottom } : null, mainScroll: document.querySelector('main').scrollTop, headerBottom, viewportHeight: innerHeight })); }
    })()`);
    await shot('interview-checked-next-1280');
    await run(`(() => {
      const i = window.__flowFirst;
      document.querySelector('[data-use-field="use_status"][data-use-table="meds"][data-row="' + (i + 1) + '"][value="not_using"]').click();
      const active = document.activeElement, rect = active.getBoundingClientRect();
      const headerBottom = Math.max(document.querySelector('main > header').getBoundingClientRect().bottom, document.querySelector('.interview-context').getBoundingClientRect().bottom);
      if (active.dataset.field !== 'meds' || active.dataset.row !== String(i + 2) || active.dataset.col !== '2' || rect.top < headerBottom - 1 || rect.bottom > innerHeight + 1 || interviewRecord.details.meds[i + 1].checked) throw Error('Not using did not focus the next visible unchecked medicine');
    })()`);
    await shot('interview-not-using-next-1280');
    await run(`(async () => {
      interviewRecord.meds = window.__flowOriginalMeds; interviewRecord.details.meds = window.__flowOriginalMeta;
      interviewChanged('meds'); renderInterview();
      if (!await saveInterview(true)) throw Error('Synthetic interview restore failed');
      document.querySelector('#section-health_check').scrollIntoView();
      window.__amhReturn = { id: interviewId, scroll: document.querySelector('main').scrollTop };
      if (!window.__amhReturn.scroll) throw Error('Interview scroll fixture not positioned');
    })()`);
    syntheticSignInListeners = ipcMain.listeners('sign-in-page');
    for (const listener of syntheticSignInListeners) ipcMain.removeListener('sign-in-page', listener);
    originalSignInUpdate = signIns.update; originalSignInReset = signIns.reset;
    signIns.update = () => {}; signIns.reset = () => {};
    sites.amh.url = 'data:text/html,' + encodeURIComponent('<!doctype html><title>AMH synthetic fixture</title><p>Local synthetic view</p>');
    await run(`navigate('amh')`, 'open synthetic AMH');
    if (!views.amh) throw Error('Synthetic AMH view missing');
    if (views.amh.webContents.isLoading()) await new Promise(resolve => views.amh.webContents.once('did-stop-loading', resolve));
    const fixtureUrl = 'data:text/html,' + encodeURIComponent('<!doctype html><title>AMH second fixture</title><p>Local synthetic history</p>');
    await views.amh.webContents.loadURL(fixtureUrl);
    if (!views.amh.webContents.navigationHistory.canGoBack() || views.amh.getBounds().y !== 255) throw Error('Synthetic AMH history or bounds missing');
    const backButton = await run(`(() => { const r = document.querySelector('#app-back').getBoundingClientRect(); if (r.bottom > 255 || r.width <= 0 || r.height <= 0) throw Error('Global Back is obscured by native view'); return { x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2) }; })()`);
    await shot('synthetic-amh-global-back-1280');
    win.webContents.sendInputEvent({ type: 'mouseDown', x: backButton.x, y: backButton.y, button: 'left', clickCount: 1 });
    win.webContents.sendInputEvent({ type: 'mouseUp', x: backButton.x, y: backButton.y, button: 'left', clickCount: 1 });
    await run(`(async () => {
      for (let n = 0; n < 100 && (page !== 'interview' || returning); n++) await new Promise(resolve => setTimeout(resolve, 50));
      if (page !== 'interview' || interviewId !== window.__amhReturn.id || Math.abs(document.querySelector('main').scrollTop - window.__amhReturn.scroll) > 2) throw Error('Global Back did not restore the exact interview and scroll');
    })()`, 'global Back from synthetic AMH');
    if (views.amh.webContents.getURL() !== fixtureUrl || !views.amh.webContents.navigationHistory.canGoBack()) throw Error('Global Back navigated browser history');
    await shot('interview-returned-from-amh-1280');
    views.amh.webContents.close(); delete views.amh;
    sites.amh.url = originalAmhUrl;
    for (const listener of syntheticSignInListeners) ipcMain.on('sign-in-page', listener);
    syntheticSignInListeners = null; signIns.update = originalSignInUpdate; signIns.reset = originalSignInReset;
    if (!process.env.HMR_SHOT_FLOW_ONLY) {
      await run(`(async () => { await navigate('intake'); if (referralRows.length !== 4) throw Error('Compact referrals lost'); document.querySelector('#referral-results article').scrollIntoView(); })()`);
      await shot('referral-review-1280');
    }
    app.exit(0);
  } catch (error) {
    console.error(`Screenshot phase: ${phase}`, error);
    if (rendererErrors.length) console.error('Recent renderer errors:', rendererErrors.join('\n'));
    app.exit(1);
  } finally {
    sites.amh.url = originalAmhUrl;
    if (syntheticSignInListeners) { for (const listener of syntheticSignInListeners) ipcMain.on('sign-in-page', listener); signIns.update = originalSignInUpdate; signIns.reset = originalSignInReset; }
    if (win && !win.isDestroyed()) win.webContents.removeListener('console-message', onConsole);
  }
}
