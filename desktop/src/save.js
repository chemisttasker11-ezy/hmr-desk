const fs = require('node:fs/promises');
const path = require('node:path');
const { createHash } = require('node:crypto');
const { fileKey } = require('./browser-queue');
function parts(filename) {
  if (typeof filename !== 'string' || !filename || filename.includes('..') || /(^[\\/]|[A-Za-z]:)/.test(filename))
    throw Error('Invalid filename');
  const p = filename.split(/[\\/]/);
  if (p.some((x) => !x || /[<>:"|?*\x00-\x1f]/.test(x))) throw Error('Invalid filename');
  return p;
}
const MONTHS = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'];
// Normalise a date of birth to YYYY-MM-DD from DD-Mon-YYYY, DD/MM/YYYY or YYYY-MM-DD; null when unreadable.
function isoDob(text) {
  const value = String(text ?? '').trim();
  let y, m, d, hit;
  if ((hit = value.match(/^(\d{1,2})[-\s/]([A-Za-z]{3})[A-Za-z]*[-\s/](\d{4})$/))) [d, m, y] = [hit[1], MONTHS.indexOf(hit[2].toLowerCase()) + 1, hit[3]];
  else if ((hit = value.match(/^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})$/))) [d, m, y] = [hit[1], hit[2], hit[3]];
  else if ((hit = value.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/))) [y, m, d] = [hit[1], hit[2], hit[3]];
  else return null;
  m = Number(m); d = Number(d); y = Number(y);
  const date = new Date(Date.UTC(y, m - 1, d));
  if (!m || date.getUTCFullYear() !== y || date.getUTCMonth() !== m - 1 || date.getUTCDate() !== d) return null;
  return `${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
}
function patientFor(folder, queue) {
  const exact = queue.filter((p) => fileKey(p.folder).toLowerCase() === folder.toLowerCase());
  if (exact.length) return exact.length === 1 ? exact[0] : null;
  // Never file on a name alone: the download folder must carry a date of birth that equals the patient's.
  const carried = folder.match(/\(([^()]*)\)\s*$/);
  const dob = carried && isoDob(carried[1]);
  if (!dob) return null;
  const words = (s) => s.toLowerCase().match(/[a-z][a-z'-]*/g) || [];
  const name = words(folder.replace(/\s*\(.*$/, ''));
  const hits = queue.filter((p) => {
    const w = words(p.folder.replace(/^XX/, '').split('_')[0]);
    return w.length && name.includes(w[0]) && name.includes(w[w.length - 1]) && isoDob(p.dob) === dob;
  });
  return hits.length === 1 ? hits[0] : null;
}
async function unique(dir, name, bytes, dedupe = false) {
  await fs.mkdir(dir, { recursive: true });
  if (dedupe)
    for (const f of await fs.readdir(dir)) {
      if (!/\.pdf$/i.test(f)) continue;
      try {
        if ((await fs.readFile(path.join(dir, f))).equals(bytes)) return { filename: f, skipped: true };
      } catch (e) {
        if (e.code !== 'EISDIR') throw e;
      }
    }
  const ext = path.extname(name),
    stem = path.basename(name, ext);
  for (let i = 1; ; i++) {
    const candidate = i === 1 ? name : `${stem} (${i})${ext}`;
    try {
      await fs.writeFile(path.join(dir, candidate), bytes, { flag: 'wx' });
      return { filename: candidate, skipped: false };
    } catch (e) {
      if (e.code !== 'EEXIST') throw e;
    }
  }
}
async function save(filename, bytes, queue, dataDir, kind = 'mhr') {
  const p = parts(filename);
  if (kind === 'mhr' && p.length === 1 && p[0] === 'HMR medicare-irn.csv') {
    const rows = csvRows(bytes.toString('utf8')).filter((row) => patientFor(row.folder, queue)?.id != null);
    const quote = (value) => '"' + String(value ?? '').replace(/"/g, '""') + '"';
    const csv = [
      'folder,medicare10,irn,status',
      ...rows.map((row) => [row.folder, row.medicare10, row.irn, row.status].map(quote).join(',')),
    ].join('\r\n');
    if (rows.length) {
      await fs.mkdir(dataDir, { recursive: true });
      await fs.writeFile(path.join(dataDir, p[0]), csv);
    }
    return { filename: p[0], csv: true };
  }
  if (kind === 'mhr' && p.length === 3 && p[0] === 'HMR Pathology' && /\.pdf$/i.test(p[2])) {
    const patient = patientFor(p[1], queue);
    const dir = patient ? path.join(patient.folder_path, 'Pathology') : path.join(dataDir, 'unfiled', p[1]);
    return { ...(await unique(dir, p[2], bytes, true)), patient, unfiled: !patient };
  }
  if (kind === 'emims' && p.length === 2 && p[0] === 'HMR Interactions' && /\.txt$/i.test(p[1])) {
    const patient = patientFor(p[1].slice(0, -4), queue);
    if (!patient?.folder_path) throw Error('Unmatched patient folder');
    const revision = /^[a-f0-9]{64}$/.test(patient.meds_revision || '') ? patient.meds_revision : 'unverified';
    const digest = createHash('sha256').update(bytes).digest('hex');
    const name = `MIMS interactions generated ${revision} ${digest}.txt`;
    await fs.mkdir(patient.folder_path, { recursive: true });
    try {
      await fs.writeFile(path.join(patient.folder_path, name), bytes, { flag: 'wx' });
      return { filename: name, skipped: false, patient };
    } catch (error) {
      if (error.code !== 'EEXIST') throw error;
      if ((await fs.readFile(path.join(patient.folder_path, name))).equals(bytes)) return { filename: name, skipped: true, patient };
      throw Error('Existing interaction result does not match its fingerprint');
    }
  }
  throw Error('Unexpected filename');
}
function csvRows(text) {
  const rows = [];
  let row = [],
    cell = '',
    quoted = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (c === '"') {
      if (quoted && text[i + 1] === '"') {
        cell += '"';
        i++;
      } else quoted = !quoted;
    } else if (c === ',' && !quoted) {
      row.push(cell);
      cell = '';
    } else if ((c === '\n' || c === '\r') && !quoted) {
      if (c === '\r' && text[i + 1] === '\n') i++;
      row.push(cell);
      rows.push(row);
      row = [];
      cell = '';
    } else cell += c;
  }
  if (cell || row.length) {
    row.push(cell);
    rows.push(row);
  }
  return rows.slice(1).map(([folder, medicare10, irn, status]) => ({ folder, medicare10, irn, status }));
}
module.exports = { parts, patientFor, unique, save, csvRows };
