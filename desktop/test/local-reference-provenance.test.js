const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require.resolve('../renderer/report-editor.js'), 'utf8');

// Only the three small reference functions are evaluated, with a minimal context. Nothing is sent or opened.
function slice(name) {
  const start = source.indexOf('function ' + name + '(');
  const asyncStart = source.indexOf('async function ' + name + '(');
  const from = asyncStart >= 0 && (start < 0 || asyncStart < start) ? asyncStart : start;
  assert.ok(from >= 0, name + ' not found');
  let depth = 0, i = source.indexOf('{', from);
  for (; i < source.length; i++) { if (source[i] === '{') depth++; else if (source[i] === '}' && --depth === 0) break; }
  return source.slice(from, i + 1);
}
function load(api) {
  const target = { textContent: '', innerHTML: '', isConnected: true };
  const ctx = {
    esc: (v) => String(v).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]),
    $: (id) => (id === 'local-ref-results' ? target : { value: '' }),
    hmr: { api }, localReferenceHits: [],
  };
  vm.createContext(ctx);
  vm.runInContext(['localReferenceHtml', 'refreshLocalReferenceStatus'].map(slice).join('\n'), ctx);
  return { ctx, target };
}
const packagedHit = (extra = {}) => ({ title: 'Synthetic heading', snippet: 'synthetic text', page: 7, section_page: 7, section_page_end: 8,
  edition: 'Synthetic (packaged tables)', page_verified: false, openable: false, ...extra });
const packagedResponse = (original) => ({ reference: { edition: 'Synthetic (packaged tables)', page_count: 9, pdf_sha256: 'a'.repeat(64), packaged: true },
  results: [packagedHit()], ...(original ? { registered_original: original } : {}) });

test('each packaged hit is labelled as unverified extraction in its own header, with no Open-original button', () => {
  const { ctx } = load(async () => ({}));
  const html = ctx.localReferenceHtml(packagedResponse({ state: 'never_registered', reason: '' }));
  assert.match(html, /Packaged extraction, NOT verified against the original page/);
  assert.match(html, /Extracted from page 7/);
  assert.doesNotMatch(html, /Physical PDF page 7/);
  assert.doesNotMatch(html, /data-local-ref-open/);
});

test('a verified hit keeps the physical page wording and its Open button', () => {
  const { ctx } = load(async () => ({}));
  const html = ctx.localReferenceHtml({ reference: { edition: 'E', page_count: 2, pdf_sha256: 'b'.repeat(64) },
    results: [packagedHit({ page_verified: undefined, openable: undefined, edition: 'E' })] });
  assert.match(html, /Physical PDF page 7/);
  assert.match(html, /data-local-ref-open/);
  assert.doesNotMatch(html, /NOT verified/);
});

test('a registered original that is unavailable shows an alert; a never-registered one does not', () => {
  const { ctx } = load(async () => ({}));
  const lost = ctx.localReferenceHtml(packagedResponse({ state: 'registered_unavailable', reason: 'Reference changed.' }));
  assert.match(lost, /role="alert"><strong>Your registered original PDF is unavailable\./);
  assert.match(lost, /Reference changed\./);
  const never = ctx.localReferenceHtml(packagedResponse({ state: 'never_registered', reason: '' }));
  assert.doesNotMatch(never, /registered original PDF is unavailable/);
});

test('the status line names an unavailable registered original, and the plain packaged line does not', async () => {
  const lostApi = async (m, url) => { if (url === '/api/reference/local') throw new Error('Local PDF cannot be read'); return packagedResponse({ state: 'registered_unavailable', reason: 'Local PDF cannot be read' }); };
  const a = load(lostApi); await a.ctx.refreshLocalReferenceStatus();
  assert.match(a.target.textContent, /^Your registered original PDF is unavailable: Local PDF cannot be read /);
  assert.match(a.target.textContent, /not re-verified against the original page/);
  const neverApi = async (m, url) => { if (url === '/api/reference/local') throw new Error('not registered'); return packagedResponse({ state: 'never_registered', reason: '' }); };
  const b = load(neverApi); await b.ctx.refreshLocalReferenceStatus();
  assert.doesNotMatch(b.target.textContent, /registered original PDF is unavailable/);
});
