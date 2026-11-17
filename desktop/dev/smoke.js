const { spawn } = require('node:child_process');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
(async () => {
  const root = fs.mkdtempSync(path.join(__dirname, 'hmr-smoke-'));
  const patient = path.join(root, 'patient');
  fs.mkdirSync(patient);
  const data = path.join(root, 'HMR-Desk-data');
  fs.mkdirSync(data);
  fs.writeFileSync(
    path.join(data, 'app-config.json'),
    JSON.stringify({ base: path.join(process.env.USERPROFILE, 'OneDrive', 'Documents', 'Desktop', 'HMR Ongoing') }),
  );
  const fixture = http.createServer((req, res) => {
    if (req.url.startsWith('/npp/getPDFContent')) {
      res.setHeader('Content-Type', 'application/pdf');
      return res.end('%PDF-1.4 synthetic');
    }
    res.setHeader('Content-Type', 'text/html');
    res.end(
      `<form><input type="text" value="fixture"><input type="password" value="fixture"><button>Sign in</button></form><div id="cdaDoc">Pathology Report 12-Nov-2026 Alex Example DoB 01-Jan-1980<table><tr><td>12 Nov 2026</td><td>Blood Count</td></tr></table><iframe src="/npp/getPDFContent"></iframe></div>`,
    );
  });
  await new Promise((ok) => fixture.listen(0, '127.0.0.1', ok));
  const port = fixture.address().port;
  const apiPort = port + 1;
  const env = {
    ...process.env,
    USERPROFILE: root,
    APPDATA: root,
    LOCALAPPDATA: root,
    TEMP: root,
    TMP: root,
    HMR_SMOKE_DATA: root,
    HMR_MOCK_PATIENT_DIR: patient,
    PORT: String(apiPort),
    HMR_API: `http://127.0.0.1:${apiPort}`,
    HMR_TOKEN: 'mock',
    HMR_SMOKE_URL: `http://127.0.0.1:${port}/portal/health-record-search/document_search/Get_Document`,
    HMR_SMOKE_PATTERNS: JSON.stringify([`http://127.0.0.1/*`]),
  };
  const api = spawn(process.execPath, [path.join(__dirname, 'mock-api.js')], { env, stdio: 'ignore' });
  await new Promise((ok, fail) => {
    api.stdout?.once('data', ok);
    setTimeout(ok, 700);
    api.once('exit', () => fail(Error('Mock API exited')));
  });
  const electron = spawn(require('electron'), ['.'], { cwd: path.join(__dirname, '..'), env, stdio: 'inherit' });
  let success = false;
  const { allowedSave, allowedFill } = require('../src/vault');
  if (
    allowedSave(env.HMR_SMOKE_URL, 'https://proda.humanservices.gov.au/', 'mhr') ||
    allowedFill(env.HMR_SMOKE_URL, `http://127.0.0.1:${port}`)
  )
    throw Error('HTTP login fixture was not refused');
  for (let i = 0; i < 100; i++) {
    await new Promise((ok) => setTimeout(ok, 200));
    if (fs.existsSync(path.join(patient, 'Pathology', '12-Nov-2026 Blood Count.pdf'))) {
      const token = fs.readFileSync(path.join(data, 'app_control_token'), 'utf8');
      const control = async (route, body) => {
        const response = await fetch('http://127.0.0.1:18768' + route, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-HMR-Control': token },
          body: JSON.stringify(body),
        });
        if (!response.ok) throw Error(`Control ${route}: ${await response.text()}`);
        return response.json();
      };
      const state = await control('/state', {});
      const buttons = await control('/page/buttons', { site: 'mhr' });
      if (state.active !== 'mhr' || !buttons.some((button) => button.id === 'hmr-save-pdf'))
        throw Error('Control fixture failed');
      success = true;
      break;
    }
    if (electron.exitCode !== null) break;
  }
  electron.kill();
  api.kill();
  fixture.close();
  try {
    fs.rmSync(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 300 });
  } catch {}
  if (!success) {
    console.error('Smoke failed: PDF not saved');
    process.exitCode = 1;
  } else console.log('Smoke passed: synthetic PDF saved; HTTP sign-in refused; control state and buttons verified');
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
