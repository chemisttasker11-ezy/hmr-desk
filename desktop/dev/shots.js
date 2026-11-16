const { spawn } = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs');
const root = fs.mkdtempSync(path.join(__dirname, 'hmr-shots-'));
const env = {
  ...process.env,
  USERPROFILE: root,
  APPDATA: root,
  LOCALAPPDATA: root,
  TEMP: root,
  TMP: root,
  HMR_SMOKE_DATA: root,
  HMR_SHOTS: '1',
  HMR_API: 'http://127.0.0.1:18765',
  HMR_TOKEN: 'mock',
  PORT: '18765',
};
const api = spawn(process.execPath, [path.join(__dirname, 'mock-api.js')], { env });
api.stdout.once('data', () => {
  const app = spawn(require('electron'), ['.'], { cwd: path.join(__dirname, '..'), env, stdio: 'inherit' });
  app.on('exit', (code, signal) => {
    api.kill();
    fs.rmSync(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 300 });
    process.exitCode = signal ? 1 : code || 0;
  });
  app.on('error', (error) => {
    console.error(error);
    api.kill();
    process.exitCode = 1;
  });
});
api.on('exit', (code) => {
  if (code) process.exitCode = code;
});
