const test = require('node:test');
const assert = require('node:assert/strict');
const fsp = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { kind, resolve } = require('../src/patient-file-open');
const H = require('../renderer/helpers.js');

async function setup() {
  const base = await fsp.mkdtemp(path.join(os.tmpdir(), 'hmr-open-'));
  const folder = path.join(base, 'Scheduled', 'Patient One');
  await fsp.mkdir(path.join(folder, 'Pathology'), { recursive: true });
  for (const f of ['referral.pdf', 'notes.txt', 'referral_source.json', '.interview.lock', 'run.exe', 'report.docx']) await fsp.writeFile(path.join(folder, f), 'x');
  await fsp.writeFile(path.join(folder, 'Pathology', 'result.pdf'), 'x');
  return { base, rel: path.join('Scheduled', 'Patient One'), folder };
}

test('only plain pdf, txt and docx names are openable, and the renderer list agrees', () => {
  assert.equal(kind('referral.pdf'), 'viewer');
  assert.equal(kind('Notes.TXT'), 'external');
  assert.equal(kind('report.docx'), 'external');
  for (const bad of ['run.exe', 'a.bat', 'x.lnk', 'referral_source.json', '.interview.lock', '', '../a.pdf', 'a/b.pdf', 'a\\b.pdf', 'a:b.pdf', 'a.pdf.exe', null, 5]) assert.equal(kind(bad), null, String(bad));
  for (const name of ['referral.pdf', 'notes.txt', 'report.docx', 'run.exe', '.interview.lock', 'referral_source.json']) assert.equal(H.fileOpenable(name), kind(name) !== null, name);
});

test('resolves files in the patient folder and Pathology subfolder, refuses everything else', async () => {
  const { base, rel } = await setup();
  const a = await resolve(fsp, base, rel, 'folder', 'referral.pdf');
  assert.equal(a.how, 'viewer'); assert.equal(path.basename(a.file), 'referral.pdf');
  assert.equal((await resolve(fsp, base, rel, 'pathology', 'result.pdf')).how, 'viewer');
  await assert.rejects(resolve(fsp, base, rel, 'folder', 'run.exe'), /not opened from here/);
  await assert.rejects(resolve(fsp, base, rel, 'folder', '../referral.pdf'), /not opened from here/);
  await assert.rejects(resolve(fsp, base, rel, 'other', 'referral.pdf'), /Unknown file list/);
  await assert.rejects(resolve(fsp, base, rel, 'folder', 'missing.pdf'), /File not found/);
  await assert.rejects(resolve(fsp, base, rel, 'pathology', 'referral.pdf'), /File not found/); // same name must be in that list
  await assert.rejects(resolve(fsp, base, '..', 'folder', 'referral.pdf'), /outside the workspace/);
});

test('a link inside the patient folder cannot reach a file outside it', async (t) => {
  const { base, rel, folder } = await setup();
  const outside = path.join(base, 'secret.pdf'); await fsp.writeFile(outside, 'x');
  try { await fsp.symlink(outside, path.join(folder, 'link.pdf')); } catch { t.skip('symlinks need a privilege on this machine'); return; }
  await assert.rejects(resolve(fsp, base, rel, 'folder', 'link.pdf'), /not inside this patient folder/);
});

test('main.js uses the policy module and checks the sender', () => {
  const main = require('node:fs').readFileSync(path.join(__dirname, '..', 'main.js'), 'utf8');
  const block = main.slice(main.indexOf("ipcMain.handle('open-patient-file'"), main.indexOf("ipcMain.on('draft-store'"));
  assert.match(block, /e\.sender !== win\.webContents/);
  assert.match(block, /require\('\.\/src\/patient-file-open'\)\.resolve/);
  assert.doesNotMatch(block, /openExternal/);
});
