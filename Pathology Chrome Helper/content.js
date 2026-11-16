// Adds HMR buttons to the portal: "Save PDF to HMR" on a report, and "Save latest of each test" on the Pathology Reports list.
// Read-only: it only opens reports the way a row click does and downloads their PDFs; it never edits or submits anything.
const LIST = '/portal/clinical_documents/pathology_report', SEARCH = '/portal/health-record-search', KEY = 'hmrBatch', RUN = 'hmrRun';
const safeName = s => s.replace(/[<>:"/\\|?*~\x00-\x1f]/g, '-').replace(/^[. ]+|[. ]+$/g, '').slice(0, 120) || 'Pathology report';
const words = s => (s || '').toLowerCase().match(/[a-z]+/g) || [];
const sleep = ms => new Promise(ok => setTimeout(ok, ms));

function readReport() {
  const doc = document.querySelector('#cdaDoc, .cdaDoc');
  if (!doc || !/Pathology Report/i.test(doc.innerText)) throw new Error('This page is not a pathology report (or it is still loading).');
  const frame = [...doc.querySelectorAll('iframe, embed, object')].map(x => x.src || x.data).find(x => x && x.includes('/npp/getPDFContent'));
  const patient = doc.innerText.match(/Pathology Report\s+(\d{1,2}-[A-Za-z]{3}-\d{4})\s+(.+?)\s+DoB\s+(\d{1,2}-[A-Za-z]{3}-\d{4})/i);
  const report = [...doc.querySelectorAll('tr')].map(r => [...r.querySelectorAll('td')].map(c => c.innerText.trim())).find(c => c.length >= 2 && /\d{1,2}\s+\w{3}\s+\d{4}/.test(c[0]));
  if (!patient || !frame || !report) throw new Error('Could not identify the patient, report date, name, and PDF on this page.');
  // The real IRN is in the report's Administrative Details: "Entitlements 40378517122 (Medicare Benefits)" = card + IRN.
  // (The search accepts any IRN 1-5, so the IRN typed there proves nothing.)
  const digits = doc.innerText.match(/([\d ]{11,15})\(Medicare/i)?.[1].replace(/\D/g, '') || '';
  const ent = digits.length === 11 ? {medicare10: digits.slice(0, 10), irn: digits[10]} : null;
  return {date: patient[1].trim(), name: patient[2].trim(), dob: patient[3].trim(), report: report[1], frame: new URL(frame, location.href), ent};
}

// One row per patient for Downloads\HMR medicare-irn.csv (Downloads root, outside the auto-filed HMR Pathology folder).
function saveCsv(results) {
  const q = v => `"${String(v ?? '').replace(/"/g, '""')}"`;
  const csv = ['folder,medicare10,irn,status', ...results.map(r => [r.folder, r.medicare10, r.irn, r.status].map(q).join(','))].join('\r\n');
  return chrome.runtime.sendMessage({url: 'data:text/csv;charset=utf-8,' + encodeURIComponent(csv), filename: 'HMR medicare-irn.csv', conflict: 'overwrite'});
}
const addResult = (run, status, ent = null) => (run.results ||= []).push({folder: HMR_PATIENTS[run.i].folder, medicare10: ent?.medicare10, irn: ent?.irn, status});

async function save(r = readReport(), folder = null) {
  if (r.frame.origin !== location.origin || r.frame.pathname !== '/npp/getPDFContent') throw new Error('Unexpected PDF address.');
  // Fetches the PDF directly, so it works even when the portal's PDF viewer stays blank.
  const response = await fetch(r.frame.href, {credentials: 'same-origin'});
  if (!response.ok) throw new Error(`PDF request failed (${response.status}).`);
  const blob = await response.blob();
  if (await blob.slice(0, 5).text() !== '%PDF-') throw new Error('The attachment was not a PDF. Nothing was saved.');
  const url = await new Promise((ok, fail) => { const f = new FileReader(); f.onload = () => ok(f.result); f.onerror = () => fail(f.error); f.readAsDataURL(new Blob([blob], {type: 'application/pdf'})); });
  // Staged under Downloads by patient folder (in a run) or name and DoB; move-reports.ps1 files them into the patient folders.
  const filename = `HMR Pathology/${safeName(folder || `${r.name} (${r.dob})`)}/${safeName(`${r.date} ${r.report}`)}.pdf`;
  const result = await chrome.runtime.sendMessage({url, filename});
  if (result.error) throw new Error(result.error);
  return `Saved: ${r.name} | DoB ${r.dob} | ${r.report} | ${r.date}\nDownloads/${result.filename}`;
}

// shortcut: keyword groups cover the common panels so labs' different names count as one test; other tests match by exact name.
const GROUPS = [[/blood count|\bfbc\b|\bcbc\b|routine haem/i, 'FBC'], [/b12|folate/i, 'B12'], [/iron|ferritin|anaemia/i, 'IRON'], [/e\/lft|elft|routine chem|general chem|biochem|electrolyte|liver function|\blft\b|\buec\b/i, 'ELFT'], [/\besr\b|sediment/i, 'ESR'],
  [/vit(amin)? ?d\b|vitd/i, 'VITD'], [/a1c/i, 'A1C'], [/lipid|cholesterol|triglycer/i, 'LIPIDS'], [/thyroid|\btsh\b/i, 'THYROID'], [/c.?reactive|\bcrp\b/i, 'CRP'],
  [/magnesium/i, 'MG'], [/trace element/i, 'TRACE'], [/histopath/i, 'HISTO'], [/prostate|\bpsa\b/i, 'PSA'], [/microalb|albumin.?creat|\bacr\b/i, 'UACR']];
const testType = name => (GROUPS.find(([re]) => re.test(name)) || [, name.replace(/^[^a-z0-9]+/i, '').toUpperCase()])[1];
const rowName = r => r.querySelector('.test-name')?.innerText.trim();

// Last 6 months; when a patient has nothing that recent, fall back to the last 12 months.
function pickLatest(months = 6) {
  const cutoff = new Date(); cutoff.setMonth(cutoff.getMonth() - months);
  const latest = new Map();
  for (const r of document.querySelectorAll('tr[data-docid]')) {
    const name = rowName(r), date = +r.dataset.sortDate, type = name && testType(name);
    if (!name || !(date >= cutoff)) continue;
    if (!latest.has(type) || date > latest.get(type).date) latest.set(type, {docid: r.dataset.docid, name, date, type});
  }
  const picked = [...latest.values()].sort((a, b) => b.date - a.date);
  return picked.length || months > 6 ? picked : pickLatest(12);
}

const load = () => JSON.parse(sessionStorage.getItem(KEY) || 'null');
const store = b => b ? sessionStorage.setItem(KEY, JSON.stringify(b)) : sessionStorage.removeItem(KEY);
const loadRun = () => JSON.parse(sessionStorage.getItem(RUN) || 'null');
const storeRun = r => r ? sessionStorage.setItem(RUN, JSON.stringify(r)) : sessionStorage.removeItem(RUN);
const irns = p => p.ihi ? [''] : p.irn || [1, 2, 3, 4, 5];
// Keeps the run's log when it stops, so the search page can still show what was done.
const stopAll = () => { const r = loadRun(); if (r) { sessionStorage.setItem('hmrLastLog', r.log.join('\n')); if (r.results?.length) saveCsv(r.results); } store(null); storeRun(null); };
const datedRows = () => [...document.querySelectorAll('tr[data-docid]')].filter(r => +r.dataset.sortDate > 0);

function addPanel(buttons) {
  const panel = document.createElement('div');
  panel.style.cssText = 'position:fixed;right:16px;bottom:16px;z-index:2147483647;background:#fff;border:2px solid #0b6e99;border-radius:8px;padding:10px;font:14px system-ui;max-width:440px;max-height:60vh;overflow:auto;box-shadow:0 2px 8px #0003';
  for (const [id, label, onclick] of buttons) {
    const b = document.createElement('button'); b.id = id; b.type = 'button'; b.textContent = label; b.onclick = onclick;
    b.style.cssText = 'font:inherit;padding:8px 14px;margin:0 6px 6px 0;cursor:pointer'; panel.append(b);
  }
  const status = document.createElement('div'); status.id = 'hmr-save-status'; status.setAttribute('role', 'status'); status.style.whiteSpace = 'pre-wrap';
  panel.append(status); document.body.append(panel);
  return status;
}

async function waitFor(fn, ms) {
  for (const end = Date.now() + ms; ; await sleep(500)) { try { const v = fn(); if (v) return v; } catch (e) { if (Date.now() > end) throw e; } if (Date.now() > end) return null; }
}

// "Run all patients": search each HMR_PATIENTS entry, check the record, run the batch, then go to the next patient.
if (location.pathname.startsWith(SEARCH)) {
  const status = addPanel([
    ['hmr-run-start', `Run all patients (${HMR_PATIENTS.length})`, () => { storeRun({i: 0, tries: 0, submitted: false, log: [], results: []}); search(); }],
    ['hmr-irn-start', 'Find Medicare IRNs only', () => { storeRun({i: 0, tries: 0, submitted: false, log: [], results: [], lookup: true}); search(); }],
    ['hmr-run-stop', 'Stop', () => { stopAll(); status.textContent = 'Stopped.'; }],
  ]);
  const lastLog = sessionStorage.getItem('hmrLastLog');
  if (lastLog && !loadRun()) status.textContent = `Last run (stopped):\n${lastLog}`;
  async function search() {
    const run = loadRun(); if (!run) return;
    if (run.submitted) { // back on the search page after a submit: that IRN did not match
      run.submitted = false; run.tries++;
      if (run.tries >= irns(HMR_PATIENTS[run.i]).length) { run.log.push(`NOT FOUND: ${HMR_PATIENTS[run.i].folder}`); addResult(run, 'NOT FOUND'); run.i++; run.tries = 0; }
      storeRun(run);
    }
    while (run.i < HMR_PATIENTS.length && !HMR_PATIENTS[run.i].ihi && !HMR_PATIENTS[run.i].medicare) { run.log.push(`SKIPPED (no Medicare or IHI): ${HMR_PATIENTS[run.i].folder}`); addResult(run, 'SKIPPED'); run.i++; storeRun(run); }
    if (run.i >= HMR_PATIENTS.length) {
      storeRun(null); sessionStorage.removeItem('hmrLastLog');
      if (run.results?.length) await saveCsv(run.results);
      status.textContent = `Run finished.${run.results?.length ? ' Medicare numbers saved to Downloads\\HMR medicare-irn.csv.' : ''}\n${run.log.join('\n')}`; return;
    }
    const p = HMR_PATIENTS[run.i], irn = irns(p)[run.tries];
    status.textContent = `Patient ${run.i + 1}/${HMR_PATIENTS.length}: ${p.folder} (IRN ${irn})\n${run.log.join('\n')}`;
    if (!await waitFor(() => document.getElementById('lname'), 15000)) return;
    const set = (id, v) => { const e = document.getElementById(id); e.value = v; e.dispatchEvent(new Event('input', {bubbles: true})); e.dispatchEvent(new Event('change', {bubbles: true})); };
    document.getElementById(p.sex === 'F' ? 'radio-sex-female' : 'radio-sex-male').click();
    document.getElementById(p.ihi ? 'radio-identifier-IHI' : 'radio-identifier-Medicare').click();
    set('lname', p.last); set('dob', p.dob); set('identifierval', p.ihi || p.medicare + irn);
    run.submitted = true; storeRun(run);
    document.getElementById('search').click();
    // A failed search may not reload the page: if still here after 20 s, count it as no match.
    setTimeout(() => { if (loadRun()?.submitted) search(); }, 20000);
  }
  search();
}

// A restricted record asks for the patient's access code: never enter one, just log it and move to the next patient.
if (location.pathname.startsWith('/portal/enterAccessCode')) {
  const run = loadRun();
  if (run?.submitted) { run.log.push(`ACCESS CODE NEEDED (record restricted): ${HMR_PATIENTS[run.i].folder}`); addResult(run, 'ACCESS CODE NEEDED'); Object.assign(run, {i: run.i + 1, tries: 0, submitted: false}); storeRun(run); location.href = SEARCH; }
}

if (location.pathname.startsWith('/portal/health-record-overview')) {
  const run = loadRun();
  if (run?.submitted) (async () => {
    const p = HMR_PATIENTS[run.i];
    const info = await waitFor(() => document.querySelector('.print__patientinfo')?.innerText, 15000) || '';
    run.submitted = false;
    // Only continue when the opened record has the referral's DOB and surname; otherwise stop the whole run.
    if (info.toUpperCase().includes(p.dob.toUpperCase()) && words(p.last).every(w => words(info).includes(w))) { run.stage = 'list'; storeRun(run); location.href = LIST; }
    else { storeRun(null); addPanel([]).textContent = `STOPPED: opened record "${info.replace(/\s+/g, ' ').trim()}" does not match ${p.folder} (${p.dob}).`; }
  })();
}

if (location.pathname.startsWith(LIST)) {
  const startBatch = (emptyList = false) => {
    const run = loadRun(), lookup = run?.stage === 'list' && run.lookup;
    // IRN lookup saves nothing: it opens the newest reports, up to 3, until one shows the Entitlements line (some labs omit it).
    const seen = new Set(), newest = datedRows().sort((a, b) => b.dataset.sortDate - a.dataset.sortDate).filter(r => !seen.has(r.dataset.docid) && seen.add(r.dataset.docid)).slice(0, 3);
    const todo = !lookup ? pickLatest() : newest.map(r => ({docid: r.dataset.docid, name: rowName(r), date: +r.dataset.sortDate, type: testType(rowName(r))}));
    store({patient: document.querySelector('.print__patientinfo')?.innerText || '', folder: run?.stage === 'list' ? HMR_PATIENTS[run.i].folder : null, todo, total: todo.length, log: [], emptyList, lookup});
    next();
  };
  const status = addPanel([
    ['hmr-batch-start', 'Save latest of each test (6 months, else 12)', () => startBatch()],
    ['hmr-batch-stop', 'Stop', () => { stopAll(); status.textContent = 'Stopped.'; }],
  ]);
  async function next() {
    const b = load(); if (!b) return;
    if (!b.todo.length) {
      store(null); status.textContent = `Done: ${b.total} test types for this patient.\n${b.log.join('\n')}`;
      const run = loadRun();
      if (run?.stage === 'list') {
        const problems = b.log.filter(l => !/^(Saved|Read)/.test(l)), p = HMR_PATIENTS[run.i];
        if (b.emptyList) problems.push('LIST EMPTY: no pathology rows loaded, check by hand');
        const card = b.ent ? ` | Medicare ${b.ent.medicare10}/${b.ent.irn}` : ' | Medicare not shown';
        run.log.push(`${p.folder}: ${b.lookup ? '' : `${b.log.filter(l => l.startsWith('Saved')).length} saved`}${card}${problems.length ? ' | ' + problems.join(' | ') : ''}`);
        addResult(run, !b.ent ? 'no report to read' : p.medicare && b.ent.medicare10 !== p.medicare ? 'found (card differs from referral)' : 'found', b.ent);
        Object.assign(run, {i: run.i + 1, tries: 0, stage: null, listRetry: false}); storeRun(run);
        location.href = SEARCH;
      }
      return;
    }
    status.textContent = `Saving ${b.total - b.todo.length + 1} of ${b.total}: ${b.todo[0].name}…\n${b.log.join('\n')}`;
    const rows = await waitFor(() => { const m = [...document.querySelectorAll('tr[data-docid]')].filter(r => r.dataset.docid === b.todo[0].docid && rowName(r) === b.todo[0].name); return m.length && m; }, 20000);
    if (!rows?.length) { b.log.push(`NOT FOUND: ${b.todo.shift().name}`); store(b); return next(); }
    (rows.find(r => r.offsetParent) || rows[0]).click();
  }
  // In a run, wait for dated rows; if the list comes up empty, reload it once before accepting "no pathology".
  if (!load() && loadRun()?.stage === 'list') waitFor(() => datedRows().length, 20000).then(n => {
    const run = loadRun();
    if (!n && !run.listRetry) { run.listRetry = true; storeRun(run); location.reload(); return; }
    startBatch(!n);
  });
  else next();
}

if (location.pathname.includes('/document_search/Get_Document')) {
  const status = addPanel([['hmr-save-pdf', 'Save PDF to HMR', async e => {
    e.target.disabled = true; status.textContent = 'Saving…';
    try { status.textContent = await save(); } catch (err) { status.textContent = `Not saved: ${err.message}`; } finally { e.target.disabled = false; }
  }]]);
  (async () => {
    const b = load(); if (!b?.todo.length) return;
    const item = b.todo[0];
    status.textContent = `Batch: saving ${item.name}…`;
    try {
      const r = await waitFor(readReport, 30000);
      // Stop everything if the report's surname and DoB differ from the record the batch started on (first names vary, e.g. Chris/Christopher).
      const recordDob = b.patient.match(/DOB:\s*(\d{1,2}-[A-Za-z]{3}-\d{4})/i)?.[1] || '', day = s => s.replace(/^0/, '').toUpperCase();
      if (!words(b.patient).includes(words(r.name).at(-1)) || day(r.dob) !== day(recordDob)) { stopAll(); status.textContent = `STOPPED: report is for ${r.name}, batch started on ${b.patient}`; return; }
      // The report's own title can differ from the list name ("Histopathology test" / "Histopathology report"): same test type is fine.
      if (r.report.toLowerCase() !== item.name.toLowerCase() && testType(r.report) !== item.type) throw new Error(`opened "${r.report}" instead`);
      if (r.ent && !b.ent) b.ent = r.ent;
      b.log.push(b.lookup ? `Read: ${r.report} | Medicare ${r.ent ? `${r.ent.medicare10}/${r.ent.irn}` : 'not shown'}` : (await save(r, b.folder)).split('\n')[0]);
      if (b.lookup && b.ent) b.todo.splice(1); // found: skip the remaining reports
    } catch (err) { b.log.push(`NOT SAVED: ${item.name} (${err.message})`); }
    b.todo.shift(); store(b);
    location.href = LIST;
  })();
}
