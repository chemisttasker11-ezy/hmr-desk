const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const fsp = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const vm = require('node:vm');
const { listFolder } = require('../src/referral-listing');
const source = fs.readFileSync(path.join(__dirname, '../renderer/intake.js'), 'utf8');

test('folder listing reports every entry it does not submit, and follows nothing', async () => {
  const dir = await fsp.mkdtemp(path.join(os.tmpdir(), 'hmr-listing-'));
  await fsp.writeFile(path.join(dir, 'a.pdf'), 'x');
  await fsp.writeFile(path.join(dir, 'B.PDF'), 'x');
  await fsp.writeFile(path.join(dir, 'notes.txt'), 'x');
  await fsp.writeFile(path.join(dir, 'scan.jpg'), 'x');
  await fsp.mkdir(path.join(dir, 'inner'));
  await fsp.writeFile(path.join(dir, 'inner', 'deep.pdf'), 'x');
  let linked = true;
  try { await fsp.symlink(path.join(dir, 'a.pdf'), path.join(dir, 'link.pdf')); } catch (_) { linked = false; }
  const out = await listFolder(dir, fsp, path);
  assert.deepEqual(out.paths.map((p) => path.basename(p)), ['B.PDF', 'a.pdf']);
  const byName = Object.fromEntries(out.skipped.map((s) => [s.name, s.reason]));
  assert.equal(byName['notes.txt'], 'not a PDF');
  assert.equal(byName['scan.jpg'], 'not a PDF');
  assert.equal(byName['inner'], 'subfolder, not scanned');
  assert.equal(byName['deep.pdf'], undefined, 'subfolders are not scanned');
  if (linked) assert.equal(byName['link.pdf'], 'link or special entry, not followed');
  assert.equal(out.found, linked ? 6 : 5);
  assert.equal(out.paths.length + out.skippedTotal, out.found, 'every discovered entry is either submitted or reported');
  await fsp.rm(dir, { recursive: true, force: true });
});

test('a long skipped list is capped but the total stays exact', async () => {
  const dir = await fsp.mkdtemp(path.join(os.tmpdir(), 'hmr-listing-'));
  for (let i = 0; i < 60; i++) await fsp.writeFile(path.join(dir, `f${i}.txt`), 'x');
  const out = await listFolder(dir, fsp, path);
  assert.equal(out.skipped.length, 50);
  assert.equal(out.skippedTotal, 60);
  await fsp.rm(dir, { recursive: true, force: true });
});

function screen() {
  const target = { innerHTML: '' };
  const ctx = vm.createContext({ document: { addEventListener() {} }, hmr: { onReferralDrop() {} }, $: () => target,
    esc: (v) => String(v).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;') });
  vm.runInContext(source, ctx);
  return { ctx, target };
}

test('the screen separates discovered, submitted, not submitted and reviewed outcomes', () => {
  const { ctx, target } = screen();
  vm.runInContext(`referralListings = [{found: 5, pdfs: 2, skippedTotal: 3, skipped: [{name: 'x.txt', reason: 'not a PDF'}, {name: 'inner', reason: 'subfolder, not scanned'}, {name: 'l', reason: 'link or special entry, not followed'}]}];
    referralRows = [{file: 'a.pdf', status: 'review', kind: 'referral', fields: {name: 'p'}}, {file: 'b.pdf', status: 'error', message: 'PDF is password protected'}]; renderReferrals()`, ctx);
  assert.match(target.innerHTML, /Discovered 5 items in the folder: 2 PDFs submitted for review, 3 not submitted/);
  assert.match(target.innerHTML, /x\.txt: not a PDF/);
  assert.match(target.innerHTML, /inner: subfolder, not scanned/);
  assert.match(target.innerHTML, /error: 1/);
  assert.match(target.innerHTML, /review: 1/);
});

test('a manual card offers skip, which removes only the card and adds no record or approval', () => {
  const { ctx, target } = screen();
  vm.runInContext("referralRows = [{file: 'finished.pdf', status: 'manual', kind: 'report', fields: {}, token: 't1'}]; renderReferrals()", ctx);
  assert.match(target.innerHTML, /data-referral-skip="0"/);
  assert.match(target.innerHTML, /Confirm and add patient/);
  assert.match(target.innerHTML, /data-manual-referral required/, 'the acknowledgement for adding stays required');
  vm.runInContext("referralRows[0].userSkipped = true; renderReferrals()", ctx);
  assert.doesNotMatch(target.innerHTML, /finished\.pdf/);
  assert.match(target.innerHTML, /skipped by you: 1/);
  assert.doesNotMatch(target.innerHTML, /rejected: [1-9]/, 'a user skip is not an engine rejection');
  assert.equal(vm.runInContext('referralRows[0].token', ctx), 't1', 'the stored token is untouched');
});

test('main.js uses the listing for folder and TO SORT scans and still sends only PDFs to the engine', () => {
  const main = fs.readFileSync(path.join(__dirname, '../main.js'), 'utf8');
  assert.match(main, /require\('\.\/src\/referral-listing'\)/);
  assert.match(main, /listFolder\(picked\.filePaths\[0\], fsp, path\)/);
  assert.match(main, /listing \? \{ \.\.\.response, listing \} : response/);
});
