'use strict';
/** Records retire, export and encrypted backup IPC. Every folder or file comes from a native dialog here, never from page code. */
const path = require('node:path');

module.exports = function registerRecordsIpc({ ipcMain, dialog, getWin, api, documentsDir }) {
  // Removing plain copies requires an explicit native confirmation, never page-supplied consent.
  ipcMain.handle('records-retire', async (e) => {
    if (e.sender !== getWin().webContents) throw Error('Invalid request');
    const choice = await dialog.showMessageBox(getWin(), { type: 'warning',
      title: 'Remove verified plain record copies?',
      message: 'Remove only plain record files whose exact bytes are already saved in the encrypted database?',
      detail: 'Stop other apps or editors changing the workspace first. Different or unreadable files stay in place for review. Word, PDF and source/import documents stay unchanged. This is ordinary file deletion, not secure erasure: old copies may remain in backups, synced storage or disk recovery. Export a readable copy first if you need one.',
      buttons: ['Cancel', 'Remove matching copies'], defaultId: 0, cancelId: 0 });
    if (choice.response !== 1) return { cancelled: true };
    return api('POST', '/api/records/retire', { confirmed: true });
  });
  // Record export gets its own channel: the folder is chosen in a native dialog here, never supplied by page code.
  ipcMain.handle('records-export', async (e, patientId) => {
    if (e.sender !== getWin().webContents || !Number.isInteger(patientId) || patientId < 0) throw Error('Invalid export request');
    const chosen = await dialog.showOpenDialog(getWin(), { title: 'Choose a folder for the exported records (the copy will not be encrypted)',
      properties: ['openDirectory', 'createDirectory'] });
    if (chosen.canceled || !chosen.filePaths[0]) return { cancelled: true };
    return api('POST', '/api/records/export', { patient_id: patientId,
      destination: path.join(chosen.filePaths[0], (patientId === 0 ? 'HMR exported shared records' : 'HMR exported records - patient ' + patientId)) });
  });
  ipcMain.handle('encrypted-backup', async (e, action, passphrase) => {
    if (e.sender !== getWin().webContents || !['create', 'restore', 'preview'].includes(action) ||
        typeof passphrase !== 'string' || passphrase.length < 12 || passphrase.length > 512)
      throw Error('Invalid backup request or passphrase (minimum 12 characters)');
    if (action === 'create') {
      const chosen = await dialog.showSaveDialog(getWin(), { title: 'Save encrypted HMR backup',
        defaultPath: path.join(documentsDir(), 'hmr-backup.hmrbak'),
        filters: [{ name: 'Encrypted HMR backup', extensions: ['hmrbak'] }] });
      if (chosen.canceled || !chosen.filePath) return { cancelled: true };
      return api('POST', '/api/backups/create', { target: chosen.filePath, passphrase });
    }
    const chosen = await dialog.showOpenDialog(getWin(), { title: 'Choose encrypted HMR backup',
      properties: ['openFile'], filters: [{ name: 'Encrypted HMR backup', extensions: ['hmrbak'] }] });
    if (chosen.canceled || !chosen.filePaths.length) return { cancelled: true };
    const inspection = await api('POST', '/api/backups/preview',
      { source: chosen.filePaths[0], passphrase });
    if (action === 'preview') return inspection;
    const confirmation = await dialog.showMessageBox(getWin(), {
      type: 'question',
      title: 'Verified isolated restore',
      message: 'Verified encrypted backup: ' + inspection.patients + ' patient records and ' +
        inspection.workspace_files + ' patient workspace files.',
      detail: 'Restore will create a separate, new folder. Your current database and workspace will NOT be replaced. Continue?',
      buttons: ['Continue isolated restore', 'Cancel'], defaultId: 1, cancelId: 1, noLink: true,
    });
    if (confirmation.response !== 0) return { cancelled: true };
    const folder = await dialog.showOpenDialog(getWin(), { title: 'Choose parent folder for isolated restore',
      properties: ['openDirectory', 'createDirectory'] });
    if (folder.canceled || !folder.filePaths.length) return { cancelled: true };
    const dest = path.join(folder.filePaths[0], 'HMR-Restored-' + Date.now());
    return api('POST', '/api/backups/restore',
      { source: chosen.filePaths[0], destination: dest, passphrase });
  });
};
