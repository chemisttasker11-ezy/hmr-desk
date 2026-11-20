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

const LOG_NAME = 'engine-startup.log';
const LOG_LIMIT = 65536;
const SAFE = /^[A-Za-z0-9_.:-]{0,40}$/;
/** Diagnostic-only lifecycle record: event names, codes and timings. Never paths, arguments, environment, tokens or response bodies. */
function lifecycleLog(dataDir) {
  const file = dataDir ? path.join(dataDir, LOG_NAME) : null;
  return (event, fields = {}) => {
    if (!file) return;
    try {
      const parts = [new Date().toISOString(), event];
      for (const [key, value] of Object.entries(fields)) {
        const text = value === null || value === undefined ? '-' : String(value);
        parts.push(key + '=' + (SAFE.test(text) ? text : 'other'));
      }
      try { if (fs.statSync(file).size > LOG_LIMIT) fs.renameSync(file, file + '.1'); } catch {}
      fs.appendFileSync(file, parts.join(' ') + '\n', { mode: 0o600 });
    } catch {}
  };
}

function bundledEngine(resourcesPath) {
  return path.join(resourcesPath, 'engine', 'hmr-engine', 'hmr-engine.exe');
}

async function start({ resourcesPath, dataDir, workspace, config, timeoutMs = 20000, onCrash = null }) {
  const engine = bundledEngine(resourcesPath);
  const log = lifecycleLog(dataDir);
  const began = Date.now();
  if (!fs.existsSync(engine)) { log('engine_missing'); throw Error('Bundled HMR clinical engine is missing. Reinstall the full application.'); }
  fs.mkdirSync(dataDir, { recursive: true });
  fs.mkdirSync(workspace, { recursive: true });
  const port = await freePort();
  const session = crypto.randomBytes(32).toString('hex');
  const tokenFile = path.join(dataDir, 'api_token');
  const endpointFile = path.join(dataDir, 'engine_endpoint.json');
  try { fs.rmSync(endpointFile, { force: true }); } catch {}
  const url = 'http://127.0.0.1:' + port;
  const child = spawn(engine, ['--data-dir', dataDir, '--workspace', workspace, '--port', String(port)], {
    windowsHide: true,
    stdio: 'ignore',
    env: { ...process.env, HMR_DATA_DIR: dataDir, HMR_WORKSPACE: workspace,
      HMR_SESSION_TOKEN: session, HMR_API_PORT: String(port),
      HMR_PDF_CONVERTER: path.join(resourcesPath, 'converter', 'libreoffice', 'program', 'soffice.exe') },
  });
  log('spawned', { pid: child.pid, timeout_ms: timeoutMs });
  let exited = false, ready = false, stopping = false;
  let attempts = 0, lastHealth = '-';
  child.once('exit', (code, signal) => log('child_exit', { code, signal, ms: Date.now() - began, ready, stopping }));
  child.once('error', error => log('child_error', { code: error && error.code, errno: error && error.errno, syscall: error && error.syscall, ms: Date.now() - began }));
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
      if (exited) { log('start_failed', { reason: 'exited', ms: Date.now() - began, attempts, last_health: lastHealth }); throw Error('Bundled engine exited during startup'); }
      attempts++;
      try {
        const response = await fetch(url + '/api/health', {
          headers: { 'X-HMR-Token': session },
          signal: AbortSignal.timeout(1000),
        });
        lastHealth = 'http_' + response.status;
        if (response.ok) {
          const status = await response.json();
          if (!status.ready || status.engine_version !== '0.1.0') {
            log('health_mismatch', { ready: status.ready, engine_version: status.engine_version });
            throw Error('Engine version mismatch. Reinstall the matching application version.'); }
          if (exited) throw Error('Bundled engine exited before readiness was established');
          log('ready', { ms: Date.now() - began, attempts, engine_version: status.engine_version });
          config.api = url;
          config.tokenFile = tokenFile;
          ready = true;
          // Live endpoint for local automation, written beside the token (never containing it).
          try { fs.writeFileSync(endpointFile, JSON.stringify({ url, pid: child.pid, app_pid: process.pid, written_at: new Date().toISOString() }), { mode: 0o600 }); } catch {}
          return { child, url, status, stop: async () => {
            stopping = true;
            try { fs.rmSync(endpointFile, { force: true }); } catch {}
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
        lastHealth = String((error.cause && error.cause.code) || error.name || 'error').slice(0, 40);
      }
      await new Promise(resolve => setTimeout(resolve, 200));
    }
    log('start_failed', { reason: 'timeout', ms: Date.now() - began, attempts, last_health: lastHealth });
    throw Error('Timed out starting the bundled clinical engine');
  } catch (error) {
    if (!exited) child.kill();
    throw error;
  }
}
module.exports = { LOG_NAME, lifecycleLog, bundledEngine, freePort, start };
