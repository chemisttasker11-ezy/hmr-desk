const { test } = require('node:test');
const assert = require('node:assert/strict');
const autorun = require('../src/autorun');

function setup({ signIn = false, button = true, tasks } = {}) {
  const calls = [],
    notes = [],
    armed = {},
    waitingTasks = {};
  let clock = 1000;
  const view = {
    webContents: {
      isLoading: () => false,
      executeJavaScript: async (src) => {
        if (src === 'CHECK') {
          if (signIn) throw Error('sign-in page');
          return true;
        }
        calls.push(src.includes('mims-run') ? 'click mims-run' : 'click other');
        return button;
      },
    },
  };
  const run = autorun({
    api: async () => ({ tasks: tasks ?? [{ state: 'waiting', waiting_for: 'emims', patient_id: 1 }] }),
    armed,
    waitingTasks,
    ensureView: (site) => (calls.push('view ' + site), view),
    arm: async (site) => {
      calls.push('arm ' + site);
      armed[site] = true;
      waitingTasks[site] = [{ id: 't1', patient_id: 1 }];
      return 'Ready';
    },
    notify: (_c, data) => notes.push(data.status),
    pageScript: () => 'CHECK',
    now: () => clock,
  });
  return { run, calls, notes, armed, waitingTasks, tick: (ms) => (clock += ms) };
}

test('a waiting eMIMS task loads the hidden tab, arms it and presses the run button', async () => {
  const s = setup();
  await s.run.tick();
  assert.deepEqual(s.calls, ['view emims', 'arm emims', 'click mims-run']);
  assert.deepEqual(s.notes, ['Started in the background']);
  await s.run.tick(); // still running: no second start
  assert.equal(s.calls.length, 3);
  s.waitingTasks.emims = []; // helper reported every task
  await s.run.tick(); // disarms, then starts again because the engine still lists a waiting task
  assert.equal(s.calls.filter((c) => c === 'arm emims').length, 2);
});

test('a sign-in page pauses that tab and backs off before retrying', async () => {
  const s = setup({ signIn: true });
  await s.run.tick();
  assert.deepEqual(s.calls, ['view emims']);
  assert.equal(s.armed.emims, false);
  assert.match(s.notes[0], /sign-in needed/);
  await s.run.tick();
  assert.equal(s.calls.length, 1);
  s.tick(5 * 60 * 1000);
  await s.run.tick();
  assert.equal(s.calls.length, 2);
});

test('nothing happens without waiting tasks, and a missing button is reported', async () => {
  const idle = setup({ tasks: [{ state: 'done', waiting_for: 'emims' }] });
  await idle.run.tick();
  assert.deepEqual(idle.calls, []);
  const nobutton = setup({ button: false });
  await nobutton.run.tick();
  assert.equal(nobutton.armed.emims, false);
  assert.match(nobutton.notes[0], /helper button not found/);
});

test('overlapping ticks waiting on slow tab do not double arm or click', async () => {
  const callbacks = [], calls = [], armed = {}, waitingTasks = {};
  const view = {
    webContents: {
      isLoading: () => true,
      once: (_event, callback) => callbacks.push(callback),
      executeJavaScript: async (code) => {
        if (code !== 'CHECK') calls.push('click');
        return true;
      },
    },
  };
  const runner = autorun({
    api: async () => ({ tasks: [{ state: 'waiting', waiting_for: 'emims' }] }),
    armed,
    waitingTasks,
    ensureView: () => view,
    arm: async (site) => {
      calls.push('arm');
      armed[site] = true;
      return 'Ready';
    },
    notify: () => {},
    pageScript: () => 'CHECK',
  });
  const first = runner.tick();
  await new Promise(setImmediate);
  const second = runner.tick();
  await new Promise(setImmediate);
  callbacks.forEach((f) => f());
  await Promise.all([first, second]);
  assert.equal(calls.filter((x) => x === 'arm').length, 1);
  assert.equal(calls.filter((x) => x === 'click').length, 1);
});
