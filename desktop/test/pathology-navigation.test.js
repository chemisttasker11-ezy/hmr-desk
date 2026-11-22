const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const H = require('../renderer/helpers');
function load() {
  const calls = [];
  const target = { scrollIntoView: () => calls.push('scrolled') };
  const context = vm.createContext({ H, esc: H.esc, page: 'interview', document: { addEventListener() {}, querySelector: () => null, getElementById: id => { calls.push(id); return id === 'section-pathology-verified' ? target : null; } } });
  vm.runInContext(fs.readFileSync(require.resolve('../renderer/interview.js'), 'utf8'), context);
  return { context, calls };
}
test('pathology navigation links point to the verified-results section and keep legacy notes', async () => {
  const { context, calls } = load();
  vm.runInContext('interviewRecord = {meds: [], details: {}}', context);
  const link = vm.runInContext('pathologySourcesLink()', context);
  assert.match(link, /href="#section-pathology-verified"/);
  assert.match(link, /Pathology sources and results/);
  const hint = vm.runInContext('pathologyLegacyHint()', context);
  assert.match(hint, /data-interview-jump="pathology-verified"/);
  assert.match(hint, /free-text pathology notes/);
  assert.equal(await vm.runInContext(`interviewClick({dataset:{interviewJump:'pathology-verified'}})`, context), true);
  assert.deepEqual(calls, ['section-pathology-verified', 'scrolled']);
});
test('source keeps the legacy pathology section and the verified section id', () => {
  const src = fs.readFileSync(require.resolve('../renderer/interview.js'), 'utf8');
  assert.match(src, /\['pathology', 'Pathology'\]/);
  assert.match(src, /id="section-pathology-verified"/);
  assert.match(src, /\+ pathologySourcesLink\(\)/);
  assert.match(src, /pathologyLegacyHint\(\) \+ input/);
});

test('pathology records table keeps one-line headers and scrolls inside its card', () => {
  const src = fs.readFileSync(require.resolve('../renderer/interview.js'), 'utf8');
  const css = fs.readFileSync(require.resolve('../style.css'), 'utf8');
  assert.match(src, /class="table-scroll pathology-records"/);
  assert.match(css, /\.pathology-records \{ overflow-x: auto/);
  assert.match(css, /\.pathology-records th \{ white-space: nowrap/);
  assert.match(css, /\.interview-context \{ flex-wrap: wrap/);
});

test('narrow-window rules: wrapping action buttons and a non-sticky Interview bar', () => {
  const css = fs.readFileSync(require.resolve('../style.css'), 'utf8');
  assert.match(css, /\.interview-section \.actions button \{ white-space: normal; max-width: 100%/);
  assert.match(css, /@media \(max-width: 800px\) \{\s*\.interview-context \{ position: static/);
});
