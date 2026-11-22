// Fictional two-patient deferred-response regression through the actual Interview click handler.
const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const H = require('../renderer/helpers');

function setup() {
  const pending = [];
  let renders = 0;
  const context = vm.createContext({
    H, esc: H.esc, page: 'interview',
    hmr: {
      api: (method, path) => new Promise((resolve, reject) =>
        pending.push({method, path, resolve, reject})),
    },
    document: { addEventListener() {} },
    errorText: error => error.message,
    recordRender: () => { renders++; },
  });
  vm.runInContext(fs.readFileSync(require.resolve('../renderer/interview.js'), 'utf8'), context);
  vm.runInContext(`interviewId='fictional-A'; interviewRequest=11; interviewRecord={}; pathologySourceIndex={sources: []}; renderInterview=()=>recordRender();`, context);
  return {context, pending, count: () => renders};
}

test('deferred pathology source reload cannot install patient A sources on patient B', async () => {
  const {context,pending,count} = setup();
  const running = vm.runInContext("interviewClick({dataset:{pathologyReloadSources:''}})", context);
  assert.equal(pending.length, 1);
  assert.match(pending[0].path, /fictional-A\/pathology\/sources/);
  vm.runInContext(`interviewId='fictional-B'; interviewRequest=12; pathologySourceIndex={sources:[{id:'fictional-B-source'}]}; interviewPathologyError='';`, context);
  pending[0].resolve({sources:[{id:'fictional-A-source'}]});
  assert.equal(await running, true);
  assert.equal(vm.runInContext('pathologySourceIndex.sources[0].id',context),'fictional-B-source');
  assert.equal(count(), 0);
});

test('deferred pathology source error cannot appear on another patient', async () => {
  const {context,pending,count} = setup();
  const running = vm.runInContext("interviewClick({dataset:{pathologyReloadSources:''}})", context);
  vm.runInContext(`interviewId='fictional-B'; interviewRequest=12; interviewPathologyError='';`, context);
  pending[0].reject(new Error('fictional source unavailable'));
  assert.equal(await running,true);
  assert.equal(vm.runInContext('interviewPathologyError',context),'');
  assert.equal(count(),0);
});

test('current patient still receives their successfully reloaded sources', async () => {
  const {context,pending,count}=setup();
  const running=vm.runInContext("interviewClick({dataset:{pathologyReloadSources:''}})",context);
  pending[0].resolve({sources:[{id:'fictional-A-source'}]});
  assert.equal(await running,true);
  assert.equal(vm.runInContext('pathologySourceIndex.sources[0].id',context),'fictional-A-source');
  assert.equal(count(),1);
});
