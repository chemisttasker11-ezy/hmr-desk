const path = require('node:path');

function shape(site, fields, folder) {
  const clean = (value) => String(value || '').trim();
  const name = clean(site === 'mhr' ? fields.last : fields.name)
    .replace(/[<>:"/\\|?*~\x00-\x1f]/g, '-')
    .replace(/^[. ]+|[. ]+$/g, '')
    .slice(0, 120);
  if (!name || !folder) throw Error('Enter a name and choose a folder');
  if (site === 'mhr') {
    const dob = clean(fields.dob),
      sex = clean(fields.sex);
    const medicare = clean(fields.medicare).replace(/\s/g, ''),
      ihi = clean(fields.ihi).replace(/\s/g, '');
    if (!dob || !sex || (!medicare && !ihi)) throw Error('Complete all required fields');
    return { folder: name, folder_path: folder, last: clean(fields.last), dob, sex, medicare, ihi, irn: '' };
  }
  if (site !== 'emims') throw Error('One-off entries are not available for this tab');
  const meds = clean(fields.meds)
    .split(/\r?\n/)
    .map((line) => line.split(',').map(clean).filter(Boolean))
    .filter((line) => line.length)
    .map((line) => (line.length === 1 ? line[0] : line));
  if (!meds.length) throw Error('Enter at least one medicine');
  return {
    folder: name,
    folder_path: folder,
    meds,
    allergies: clean(fields.allergies).split(/\r?\n/).map(clean).filter(Boolean),
  };
}

function selectQueue(site, entries, tasks) {
  const waiting = tasks.filter((task) => task.state === 'waiting' && task.waiting_for === site);
  const selected = waiting.length ? entries.filter((entry) => waiting.some((t) => t.patient_id === entry.id)) : entries;
  return { entries: selected, waiting };
}

function fileKey(folder) {
  return path.win32.basename(folder).replace(/[<>:"|?*]/g, '_');
}
module.exports = { shape, selectQueue, fileKey };
