'use strict';
/** Electron owns one private authenticated loopback engine. No shell, no system Python. */
const { spawn } = require('node:child_process');
const crypto = require('node:crypto');
const net = require('node:net');
const fs = require('node:fs');
const path = require('node:path');

async function freePort() {
  const server = net.createServer();
  return await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const port = server.address().port;
      server.close(error => error ? reject(error) : resolve(port));
    });
  });
}

function bundledEngine(resourcesPath) {
  return path.join(resourcesPath, 'engine', 'hmr-engine', 'hmr-engine.exe');
}

async function start({ resourcesPath, dataDir, workspace, config, timeoutMs = 20000, onCrash = null }) {
  const engine = bundledEngine(resourcesPath);
  if (!fs.existsSync(engine)) throw Error('Bundled HMR clinical engine is missing. Reinstall the full application.');
  fs.mkdirSync(dataDir, { recursive: true });
  fs.mkdirSync(workspace, { recursive: true });
  const port = await freePort();
  const session = crypto.randomBytes(32).toString('hex');
  const tokenFile = path.join(dataDir, 'api_token');
  const url = 'http://127.0.0.1:' + port;
  const child = spawn(engine, ['--data-dir', dataDir, '--workspace', workspace, '--port', String(port)], {
    windowsHide: true,
    stdio: 'ignore',
    env: { ...process.env, HMR_DATA_DIR: dataDir, HMR_WORKSPACE: workspace,
      HMR_SESSION_TOKEN: session, HMR_API_PORT: String(port),
      HMR_PDF_CONVERTER: path.join(resourcesPath, 'converter', 'libreoffice', 'program', 'soffice.exe') },
  });
  let exited = false, ready = false, stopping = false;
  const failed = () => {
    exited = true;
    if (ready && !stopping && typeof onCrash === 'function')
      Promise.resolve().then(() => onCrash()).catch(() => {});
  };
  child.once('exit', failed);
  child.once('error', failed);
  const deadline = Date.now() + timeoutMs;
  try {
    while (Date.now() < deadline) {
      if (exited) throw Error('Bundled engine exited during startup');
      try {
        const response = await fetch(url + '/api/health', {
          headers: { 'X-HMR-Token': session },
          signal: AbortSignal.timeout(1000),
        });
        if (response.ok) {
          const status = await response.json();
          if (!status.ready || status.engine_version !== '0.1.0')
            throw Error('Engine version mismatch. Reinstall the matching application version.');
          if (exited) throw Error('Bundled engine exited before readiness was established');
          config.api = url;
          config.tokenFile = tokenFile;
          ready = true;
          return { child, url, status, stop: async () => {
            stopping = true;
            if (exited) return;
            try {
              await fetch(url + '/api/engine/stop', {
                method: 'POST', headers: { 'X-HMR-Token': session, 'Content-Type': 'application/json' },
                body: '{}', signal: AbortSignal.timeout(1500),
              });
              await Promise.race([
                new Promise(resolve => child.once('exit', resolve)),
                new Promise(resolve => setTimeout(resolve, 2500)),
              ]);
            } catch {}
            if (!exited) child.kill();
          } };
        }
      } catch (error) {
        if (error.message.startsWith('Engine version mismatch')) throw error;
      }
      await new Promise(resolve => setTimeout(resolve, 200));
    }
    throw Error('Timed out starting the bundled clinical engine');
  } catch (error) {
    if (!exited) child.kill();
    throw error;
  }
}
module.exports = { bundledEngine, freePort, start };
