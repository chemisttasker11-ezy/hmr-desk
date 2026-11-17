const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { save, parts, csvRows } = require('../src/save');
test('files PDFs without overwriting and skips identical bytes', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'hmr-save-'));
  try {
    const folder = path.join(root, 'patient');
    const queue = [{ id: 1, folder: 'Alex Example', folder_path: folder }];
    const a = await save('HMR Pathology/Alex Example/report.pdf', Buffer.from('one'), queue, root);
    assert.equal(a.filename, 'report.pdf');
    const b = await save('HMR Pathology/Alex Example/report.pdf', Buffer.from('two'), queue, root);
    assert.equal(b.filename, 'report (2).pdf');
    const c = await save('HMR Pathology/Alex Example/other.pdf', Buffer.from('one'), queue, root);
    assert.equal(c.skipped, true);
    assert.equal(c.filename, 'report.pdf');
    const d = await save('HMR Pathology/Unknown/other.pdf', Buffer.from('x'), queue, root);
    assert.equal(d.unfiled, true);
    assert.equal((await fs.readFile(path.join(root, 'unfiled', 'Unknown', 'other.pdf'))).toString(), 'x');
  } finally {
    await fs.rm(root, { recursive: true, force: true });
  }
});
test('rejects unsafe paths', () => {
  for (const name of ['../x', 'C:/x', '/absolute', 'x/../../y', 'x\\..\\y']) assert.throws(() => parts(name));
});
test('reads quoted CSV rows', () =>
  assert.deepEqual(csvRows('folder,medicare10,irn,status\r\n"Example, Alex","123","1","found"'), [
    { folder: 'Example, Alex', medicare10: '123', irn: '1', status: 'found' },
  ]));

test('saves one-off interactions without an engine id and never overwrites', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'hmr-one-off-'));
  try {
    const queue = [{ folder: 'Example', folder_path: root }];
    const first = await save('HMR Interactions/Example.txt', Buffer.from('one'), queue, root, 'emims');
    const second = await save('HMR Interactions/Example.txt', Buffer.from('two'), queue, root, 'emims');
    assert.match(first.filename, /^MIMS interactions generated unverified [a-f0-9]{64}\.txt$/);
    assert.match(second.filename, /^MIMS interactions generated unverified [a-f0-9]{64}\.txt$/);
    assert.equal(await fs.readFile(path.join(root, first.filename), 'utf8'), 'one');
    assert.equal(await fs.readFile(path.join(root, second.filename), 'utf8'), 'two');
  } finally {
    await fs.rm(root, { recursive: true, force: true });
  }
});

test('one-off pathology files stay in the chosen folder and are excluded from the engine CSV', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'hmr-one-off-'));
  try {
    const folder = path.join(root, 'chosen');
    const queue = [
      { folder: 'Example', folder_path: folder },
      { id: 1, folder: 'Other', folder_path: root },
    ];
    await save('HMR Pathology/Example/report.pdf', Buffer.from('pdf'), queue, root);
    assert.equal(await fs.readFile(path.join(folder, 'Pathology', 'report.pdf'), 'utf8'), 'pdf');
    await save(
      'HMR medicare-irn.csv',
      Buffer.from('folder,medicare10,irn,status\nExample,1,1,found\nOther,2,2,found'),
      queue,
      root,
    );
    const csv = await fs.readFile(path.join(root, 'HMR medicare-irn.csv'), 'utf8');
    assert(!csv.includes('Example'));
    assert(csv.includes('Other'));
  } finally {
    await fs.rm(root, { recursive: true, force: true });
  }
});


test('binds generated output to the queued medicine revision without replacing old results', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'hmr-mims-'));
  try {
    const old = path.join(root, 'MIMS interactions.txt');
    await fs.writeFile(old, 'previous result');
    const first = [{ id: 1, folder: 'Example', folder_path: root, meds_revision: 'a'.repeat(64) }];
    const second = [{ ...first[0], meds_revision: 'b'.repeat(64) }];
    const delayed = await save('HMR Interactions/Example.txt', Buffer.from('old result'), first, root, 'emims');
    const current = await save('HMR Interactions/Example.txt', Buffer.from('new result'), second, root, 'emims');
    assert.match(delayed.filename, /^MIMS interactions generated a{64} [a-f0-9]{64}\.txt$/);
    assert.match(current.filename, /^MIMS interactions generated b{64} [a-f0-9]{64}\.txt$/);
    assert.equal(await fs.readFile(old, 'utf8'), 'previous result');
    assert.equal(await fs.readFile(path.join(root, delayed.filename), 'utf8'), 'old result');
    assert.equal(await fs.readFile(path.join(root, current.filename), 'utf8'), 'new result');
  } finally { await fs.rm(root, { recursive: true, force: true }); }
});
