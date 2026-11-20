'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');

test('GP Plan toggle appears in dedicated Reports settings and defaults off', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'renderer', 'settings.js'), 'utf8');
  const context = { esc: (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;') };
  vm.createContext(context);
  vm.runInContext(source, context);
  const html = vm.runInContext(`practiceSettings = [{
    key: 'report_include_gp_plan', type: 'bool', value: false,
    default: false, label: 'Add blank GP Plan column to HMR medicine table'
  }]; practiceFields();`, context);
  assert.match(html, /<h2>Reports<\/h2>/);
  assert.match(html, /id="setting-report_include_gp_plan"/);
  assert.doesNotMatch(html, /id="setting-report_include_gp_plan" type="checkbox" checked/);
  assert.match(html, /only newly generated reports/);
  const active = vm.runInContext(`practiceSettings[0].value = true; practiceFields();`, context);
  assert.match(active, /id="setting-report_include_gp_plan" type="checkbox" checked/);
});
