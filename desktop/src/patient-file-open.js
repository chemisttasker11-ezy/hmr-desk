// Safe open of one file listed in a patient's Files tab. Only plain files directly in the patient folder or its Pathology
// subfolder, by exact name, with a short allow-list of document types. Never executes anything: unknown types are refused.
const path = require('node:path');
const { inside } = require('./folder');
const VIEWER = new Set(['.pdf']);        // opens in the bundled locked-down PDF viewer
const EXTERNAL = new Set(['.txt', '.docx']); // opens with the installed Windows app for that type
const SECTIONS = { folder: '', pathology: 'Pathology' };

function kind(name) {
  if (typeof name !== 'string' || !name || name.startsWith('.') || path.basename(name) !== name || /[<>:"/\\|?*\u0000-\u001f]/.test(name)) return null;
  const ext = path.extname(name).toLowerCase();
  return VIEWER.has(ext) ? 'viewer' : EXTERNAL.has(ext) ? 'external' : null;
}

async function resolve(fsp, base, patientFolder, section, name) {
  if (!Object.hasOwn(SECTIONS, section)) throw Error('Unknown file list');
  const how = kind(name);
  if (!how) throw Error('This file type is not opened from here. Open the folder to use it.');
  const realBase = await fsp.realpath(base);
  const folder = await fsp.realpath(path.resolve(realBase, patientFolder));
  if (!inside(realBase, folder)) throw Error('Patient folder is outside the workspace');
  const dir = SECTIONS[section] ? await fsp.realpath(path.join(folder, SECTIONS[section])) : folder;
  if (dir !== folder && !inside(folder, dir)) throw Error('File is outside this patient folder');
  let file;
  try { file = await fsp.realpath(path.join(dir, name)); } catch { throw Error('File not found'); }
  if (path.dirname(file) !== dir || !inside(realBase, file) || !(await fsp.stat(file)).isFile()) throw Error('File is not inside this patient folder');
  return { file, how };
}
module.exports = { kind, resolve };
