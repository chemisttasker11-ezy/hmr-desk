// Adds a "Run lists" button to the eMIMSplus Interaction Checker. For each entry in MIMS_LISTS (lists.js) it clears the
// checker, adds every medicine and allergy, runs the check, and saves Downloads\HMR Interactions\<folder name>.txt.
const sleep = ms => new Promise(r => setTimeout(r, ms));
const until = async (fn, ms = 15000) => { for (let t = 0; t < ms; t += 250) { const v = fn(); if (v) return v; await sleep(250); } return null; };
const setValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
const fields = () => document.querySelectorAll('#Interaction-Search input[role=combobox]'); // [0] medicines, [1] allergies

// Only a single exact displayed name is safe to select automatically.
// Salt/form/strength/prefix and multiple-option matches require manual review.
function pick(options, query) {
  const normal = s => s.trim().replace(/\s+/g, ' ').toLowerCase();
  const exact = options.filter(o => normal(o.querySelector('[title]')?.getAttribute('title') || o.innerText) === normal(query));
  return exact.length === 1 ? exact[0] : null;
}

async function add(input, name) {
  input.focus(); setValue.call(input, name);
  input.dispatchEvent(new Event('input', {bubbles: true}));
  input.dispatchEvent(new KeyboardEvent('keyup', {key: name.slice(-1), bubbles: true})); // the search runs on keyup
  const box = () => document.getElementById(input.getAttribute('aria-controls'));
  // Only accept options for this query: the previous name's list can still be showing for a moment.
  // A word must start with the query's first 4 letters ("ceno" must not match "undecenoate").
  const q = new RegExp('\\b' + name.toLowerCase().slice(0, 4).replace(/[^\w]/g, '\\$&')), title = o => (o.querySelector('[title]')?.getAttribute('title') || o.innerText).toLowerCase();
  const opts = await until(() => { const o = [...(box()?.querySelectorAll('li[role=option]') || [])].filter(o => q.test(title(o))); return o.length && o; }, 6000);
  if (!opts) { setValue.call(input, ''); input.dispatchEvent(new Event('input', {bubbles: true})); return null; }
  const o = pick(opts, name);
  if (!o) { setValue.call(input, ''); input.dispatchEvent(new Event('input', {bubbles: true})); return null; }
  const label = (o.querySelector('[title]')?.getAttribute('title') || o.innerText).trim();
  o.click(); await sleep(600);
  return label;
}

// Opens each result row's info dialog and keeps MIMS's own wording: summary, actions to be taken, details.
async function details() {
  const out = [], trs = [...document.querySelectorAll('table tr')].slice(1);
  for (const tr of trs) {
    const c = [...tr.cells].map(x => x.innerText.trim().replace(/\s+/g, ' '));
    const line = `${c[0]} + ${c[2]} | ${c[4]} | ${c[5]}`;
    if (out.some(o => o.startsWith(line))) continue; // same pair listed per route
    const icon = tr.querySelector('i'); (icon?.closest('button,a,[role=button]') || icon)?.click();
    const modal = await until(() => document.querySelector('.modal.show'), 5000);
    let text = '';
    if (!modal) throw Error('Interaction details unavailable; result incomplete');
    if (modal) {
      const t = modal.innerText.replace(/\r/g, '').split('\n').map(s => s.trim()).filter(Boolean);
      const at = k => t.findIndex(s => s.startsWith(k));
      const block = (a, b) => (at(a) < 0 ? [] : t.slice(at(a) + 1, at(b) > at(a) ? at(b) : undefined));
      const summary = t[at('Severity') - 1] || '';
      text = [`   ${summary}`, `   Action: ${block('Actions to be taken', 'Drug interactions details').join(' ')}`,
              `   Detail: ${block('Drug interactions details', 'References').join(' ')}`].join('\r\n');
      const bs = modal.querySelectorAll('.ms-auto button'); bs[bs.length - 1]?.click(); // last button is X (first is print)
      if (!await until(() => !document.querySelector('.modal.show'), 3000)) throw Error('Interaction details did not close; result incomplete');
    }
    out.push(line + (text ? '\r\n' + text : ''));
  }
  return out;
}

const rows = () => [...document.querySelectorAll('table tr')].slice(1)
  .map(r => [...r.cells].map(c => c.innerText.trim().replace(/\s+/g, ' ')))
  .map(c => `${c[0]} + ${c[2]} | ${c[4]} | ${c[5]}`).filter((r, i, all) => all.indexOf(r) === i); // same pair listed per route

async function runOne(list) {
  const clear = document.getElementById('ClearAll');
  if (!clear || fields().length !== 2 || !Array.isArray(list.meds) || !list.meds.length) throw Error('Interaction checker UI or medicine list unavailable; check manually');
  clear.click(); await sleep(1000);
  if (rows().length) throw Error('Previous interaction results did not clear; check manually');
  const out = [`Folder: ${list.folder}`, `Checked: ${new Date().toLocaleString('en-AU')} (eMIMSplus MIMS Interaction Checker)`, ''];
  const entered = [], missing = [];
  for (const m of list.meds) { // m is a name or [name, fallback brand/alias, ...]: try each until MIMS finds one
    const tries = [].concat(m, [].concat(m)[0]); let got = null, used; // generic retried last: a search can miss once
    for (used of tries) if ((got = await add(fields()[0], used))) break;
    got ? entered.push(`${tries[0]}${used !== tries[0] ? ` (as ${used})` : ''} -> ${got}`) : missing.push(tries.slice(0, -1).join(' / '));
  }
  for (const a of list.allergies || []) { const got = await add(fields()[1], a); got ? entered.push(`allergy ${a} -> ${got}`) : missing.push(`allergy ${a}`); }
  if (missing.length) throw Error('Incomplete eMIMS check: no unique exact match for ' + missing.join('; ') + '. Review mappings manually');
  const check = [...document.querySelectorAll('button')].find(b => b.innerText.trim() === 'Check Interaction');
  if (!check) throw Error('Interaction checker control unavailable; check manually');
  const emptyMessage = text => text.split(/\r?\n/).some(line => /^(?:No (?:drug )?interactions?(?: (?:found|detected|identified))?|No results(?: found)?)\.?$/i.test(line.trim()));
  const previousEmpty = emptyMessage(document.body.innerText);
  let sawLoading = false;
  check.click();
  // A timeout, missing table or unrecognised UI is never an empty check.
  const ready = await until(() => {
    const text = document.body.innerText;
    if (/Loading/i.test(text)) { sawLoading = true; return null; }
    if (/Showing results/i.test(text) && rows().length) return 'results';
    return emptyMessage(text) && (!previousEmpty || sawLoading) ? 'empty' : null;
  }, 20000);
  if (!ready) throw Error('eMIMS result not verified: timed out or unrecognised UI. No completed result saved');
  [...document.querySelectorAll('button')].find(b => b.innerText.trim().startsWith('Drug Interactions'))?.click(); // previous patient may have left the Allergy tab open
  await sleep(800);
  const resultRows = rows();
  if ((ready === 'results' && !resultRows.length) || (ready === 'empty' && resultRows.length)) throw Error('eMIMS result state changed; check manually');
  const det = resultRows.length ? await details() : ['none listed by MIMS'];
  out.push('DRUG INTERACTIONS (pair | severity | documentation, then MIMS wording):', ...det, '');
  if ((list.allergies || []).length) {
    const tab = [...document.querySelectorAll('button')].find(b => b.innerText.trim().startsWith('Allergy Check'));
    if (!tab) throw Error('Allergy check unavailable; result incomplete');
    tab.click(); await sleep(2500);
    const panel = tab && document.getElementById(tab.getAttribute('aria-controls'));
    const text = (panel?.innerText || '').split(/The absence of a drug allergy|Disclaimer/)[0].replace('Allergy Check Results', '').trim();
    if (!text || /Loading/i.test(text)) throw Error('Allergy result not verified; result incomplete');
    out.push('ALLERGY CHECK:', text, '');
  }
  out.push('ENTERED:', ...entered, '', 'NOT FOUND IN MIMS (check by hand):', ...(missing.length ? missing : ['none']), '',
    'MIMS does not flag same-class duplication or cumulative sedative/anticholinergic/serotonergic/potassium load: hand-check those.');
  const name = list.folder.split(/[\\/]/).pop().replace(/[<>:"|?*]/g, '_');
  const url = 'data:text/plain;charset=utf-8,' + encodeURIComponent(out.join('\r\n'));
  return chrome.runtime.sendMessage({url, filename: `HMR Interactions/${name}.txt`});
}

if (typeof MIMS_LISTS !== 'undefined' && MIMS_LISTS.length) {
  const b = document.createElement('button');
  b.textContent = `Run ${MIMS_LISTS.length} interaction list(s)`;
  b.style.cssText = 'position:fixed;bottom:16px;left:16px;z-index:99999;max-width:calc(100vw - 32px);max-height:40vh;overflow:auto;white-space:normal;text-align:left;padding:10px 14px;background:#0b5394;color:#fff;border:0;border-radius:6px;font:14px sans-serif;cursor:pointer';
  b.onclick = async () => {
    if (!location.pathname.startsWith('/interactions')) { location.href = '/interactions'; return; }
    b.disabled = true;
    const failures = [];
    for (const [i, list] of MIMS_LISTS.entries()) {
      b.textContent = `Checking ${i + 1}/${MIMS_LISTS.length}: ${list.folder.split(/[\\/]/).pop()}`;
      const r = await runOne(list).catch(e => ({error: e.message}));
      if (r?.error) { failures.push(`${list.folder.split(/[\\/]/).pop()}: ${r.error}`); console.warn('MIMS helper', list.folder, r.error); }
    }
    b.textContent = failures.length ? `Incomplete: ${failures.length}/${MIMS_LISTS.length} list(s) need manual review. ${failures.join(' | ')}` : `Done: ${MIMS_LISTS.length} file(s) in Downloads\\HMR Interactions`; b.disabled = false;
  };
  document.body.appendChild(b);
                                                            }
