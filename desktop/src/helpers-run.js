const fsp = require('node:fs/promises');
const path = require('node:path');
const { randomUUID } = require('node:crypto');
const { matches, patterns, assemble } = require('./injection');
const { save, csvRows, patientFor } = require('./save');

module.exports = ({ views, armed, queues, saved, sites, config, dataDir, api, notify, waitingTasks }) => {
  let mimsRun = null, mimsGeneration = 0;
  const sourceDir = site => path.join(process.resourcesPath ? path.join(process.resourcesPath, 'browser-helpers') : config.base, sites[site].dir);
  function allowed(site, sender) {
    const manifest = path.join(sourceDir(site), 'manifest.json');
    const list =
      process.env.HMR_SMOKE_PATTERNS && process.env.HMR_SMOKE_URL
        ? JSON.parse(process.env.HMR_SMOKE_PATTERNS)
        : patterns(manifest);
    return matches(sender.getURL(), list);
  }
  async function cancel(site) {
    if (site !== 'emims') return;
    ++mimsGeneration; mimsRun = null;
    const view = views[site];
    if (view && !view.webContents.isDestroyed()) await view.webContents.executeJavaScript("window.__hmrMimsRun = null; document.getElementById('mims-run')?.remove();");
  }
  async function inject(site) {
    const view = views[site], spec = sites[site];
    if (!view || !spec.dir || !armed[site] || !allowed(site, view.webContents)) return;
    const generation = site === 'emims' ? ++mimsGeneration : 0;
    if (site === 'emims') mimsRun = null;
    const queue = site === 'emims' ? JSON.parse(JSON.stringify(queues[site])) : queues[site];
    const source = await fsp.readFile(path.join(sourceDir(site), 'content.js'), 'utf8');
    if (!armed[site] || (site === 'emims' && generation !== mimsGeneration)) return;
    const token = site === 'emims' ? randomUUID() : undefined;
    const script = assemble(spec.key, queue, source, token);
    if (site === 'emims') mimsRun = { token, queue, generation };
    await view.webContents.executeJavaScript(script);
  }
  async function report(site, patient, state, output, mimsResult) {
    if (patient?.id == null) return;
    const tasks = (waitingTasks[site] || []).filter((task) => task.patient_id === patient.id);
    for (const task of tasks) {
      const result = await api('POST', `/api/run/${encodeURIComponent(task.id)}/result`, { state, output, ...(mimsResult ? { mims_result: mimsResult } : {}) });
      if (result?.state === 'failed') { state = 'failed'; output = result.output; }
      waitingTasks[site] = waitingTasks[site].filter((item) => item.id !== task.id);
    }
    return { state, output };
  }
  async function saveHelper(e, message) {
    const site = Object.keys(views).find((key) => views[key].webContents === e.sender);
    if (!site || !armed[site]) return { error: 'Helper is not armed' };
    try {
      if (!allowed(site, e.sender)) throw Error('Page is not permitted');
      const run = site === 'emims' ? mimsRun : null;
      if (site === 'emims' && (!run || message?.hmrRun !== run.token)) throw Error('MIMS helper run is no longer active');
      if (site === 'ppa' && message?.type === 'filled') {
        if (!Number.isInteger(message.index) || !queues.ppa[message.index]) throw Error('Invalid claim');
        await report(site, queues.ppa[message.index], 'done', 'Form filled; check and submit manually.');
        notify('result', { site, status: 'Form filled; check and submit manually.' });
        return { ok: true };
      }
      if (!['mhr', 'emims'].includes(site) || typeof message?.url !== 'string' || typeof message.filename !== 'string')
        throw Error('Invalid download');
      let bytes;
      if (message.url.startsWith('data:')) {
        const m = /^data:([^,]*?),(.*)$/s.exec(message.url);
        if (!m) throw Error('Invalid data URL');
        bytes = m[1].endsWith(';base64') ? Buffer.from(m[2], 'base64') : Buffer.from(decodeURIComponent(m[2]));
      } else {
        const u = new URL(message.url),
          page = new URL(e.sender.getURL());
        if (u.origin !== page.origin || !['https:', 'http:'].includes(u.protocol)) throw Error('Invalid download URL');
        const response = await e.sender.session.fetch(u.href);
        if (!response.ok) throw Error(`Download failed (${response.status})`);
        bytes = Buffer.from(await response.arrayBuffer());
      }
      if (site === 'emims' && (mimsRun !== run || !armed[site])) throw Error('MIMS helper run is no longer active');
      const result = await save(message.filename, bytes, site === 'emims' ? run.queue : queues[site], dataDir, site);
      if (site === 'emims' && (mimsRun !== run || !armed[site])) throw Error('MIMS helper run is no longer active; result retained for review');
      let reported;
      if (result.patient?.id != null) {
        const id = result.patient.id;
        saved[id] ||= [];
        if (!saved[id].includes(result.filename)) saved[id].push(result.filename);
        if (site === 'mhr') await api('POST', '/api/pathology/result', { id, status: 'saved', saved: saved[id] });
        if (site === 'emims') reported = await report(site, result.patient, 'done', `Saved ${result.filename}`, result.filename);
      }
      if (result.csv)
        for (const row of csvRows(bytes.toString('utf8'))) {
          const patient = patientFor(row.folder, queues.mhr);
          if (patient?.id != null) {
            await api('POST', '/api/pathology/result', {
              id: patient.id,
              status: row.status,
              saved: saved[patient.id] || [],
              medicare10: row.medicare10,
              irn: row.irn,
            });
            const success = /^found/i.test(row.status);
            await report('mhr', patient, success ? 'done' : 'failed', row.status);
          }
          notify('result', { site, patient: row.folder, status: row.status });
        }
      notify('result', {
        site,
        patient: result.patient?.folder || '',
        status: reported?.state === 'failed' ? reported.output : result.unfiled ? 'Unfiled' : result.skipped ? 'Already saved' : 'Saved',
        filename: result.filename,
      });
      return { filename: result.filename };
    } catch (err) {
      notify('result', { site, status: err.message });
      return { error: err.message };
    }
  }
  return { inject, saveHelper, cancel };
};
