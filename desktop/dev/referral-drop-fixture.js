// Manual integration fixture: run with the project's Electron binary, never the live app.
const {app, BrowserWindow, ipcMain} = require('electron');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'hmr-referral-drop-'));
const pdf = path.join(dir, 'synthetic.pdf');
const html = path.join(dir, 'drop.html');
fs.writeFileSync(pdf, '%PDF-1.4\nsynthetic fixture\n%%EOF');
fs.writeFileSync(html, '<input id="file" type="file"><div id="referral-drop">Drop</div>');
let win;
ipcMain.handle('referral-drop', (_event, paths) => {
  if (paths.length !== 1 || path.resolve(paths[0]) !== path.resolve(pdf)) throw Error('Native File path was not preserved');
  return {rows:[{file:'synthetic.pdf',status:'review'}]};
});
app.whenReady().then(async () => {
  win = new BrowserWindow({show:false, webPreferences:{contextIsolation:true, nodeIntegration:false, preload:path.join(__dirname,'..','preload.js')}});
  await win.loadFile(html);
  const wc = win.webContents;
  wc.debugger.attach('1.3');
  const root = await wc.debugger.sendCommand('DOM.getDocument');
  const input = await wc.debugger.sendCommand('DOM.querySelector', {nodeId:root.root.nodeId, selector:'#file'});
  await wc.debugger.sendCommand('DOM.setFileInputFiles', {nodeId:input.nodeId, files:[pdf]});
  const success = await wc.executeJavaScript(`new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error('drop result timed out')), 5000);
    window.hmr.onReferralDrop(result => { if (result.error) { clearTimeout(timeout); reject(new Error(result.error)); } else if (result.rows) { clearTimeout(timeout); resolve(result.rows[0].file); } });
    const transfer = new DataTransfer(); transfer.items.add(document.querySelector('#file').files[0]);
    document.querySelector('#referral-drop').dispatchEvent(new DragEvent('drop', {bubbles:true, cancelable:true, dataTransfer:transfer}));
  })`);
  if (success !== 'synthetic.pdf') throw Error('Unexpected renderer result');
  console.log('PASS: native File path crosses isolated preload via drop');
  wc.debugger.detach(); win.destroy(); fs.rmSync(dir, {recursive:true, force:true}); app.exit(0);
}).catch(error => { console.error(error); if (win) win.destroy(); fs.rmSync(dir, {recursive:true, force:true}); app.exit(1); });
