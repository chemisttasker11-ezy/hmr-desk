const test = require('node:test');
const assert = require('node:assert/strict');
const H = require('../renderer/helpers.js');
const ready = { items: [], clinically_ready: null };
test('current wording says what is covered and excludes unsaved editor changes', () => {
  const html = H.reportStatusHtml({ status: 'current', reasons: [], signed_off: false, signed_version_intact: null, readiness: ready });
  assert.match(html, /report text saved when it was built/);
  assert.match(html, /not yet saved in the editor are not included/);
});
test('pharmacist details change is named as a reason', () => {
  const html = H.reportStatusHtml({ status: 'outdated', reasons: ['pharmacist_identity_changed'], signed_off: false, signed_version_intact: null, readiness: ready });
  assert.match(html, /pharmacist details in Settings changed/);
});
