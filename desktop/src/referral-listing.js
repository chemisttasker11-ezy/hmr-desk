// Lists a folder for referral review and says what it left out, so a skipped file is never invisible.
// Top level only. Subfolders and links or special entries are reported, never scanned or followed.
const MAX_SKIPPED_SHOWN = 50;

async function listFolder(dir, fsp, path) {
  const entries = await fsp.readdir(dir, { withFileTypes: true });
  const paths = [], skipped = [];
  const isPdf = (name) => name.toLowerCase().endsWith('.pdf');
  for (const entry of entries) {
    const name = entry.name;
    if (entry.isDirectory()) { skipped.push({ name, reason: 'subfolder, not scanned' }); continue; }
    if (entry.isFile()) {
      if (isPdf(name)) paths.push(path.join(dir, name));
      else skipped.push({ name, reason: 'not a PDF' });
      continue;
    }
    // Link, shortcut, cloud placeholder or other special entry. Not followed: traversal scope is unchanged, so it is reported, not read.
    skipped.push({ name, reason: 'link or special entry, not followed' });
  }
  paths.sort();
  return { paths, skipped: skipped.slice(0, MAX_SKIPPED_SHOWN), skippedTotal: skipped.length, found: entries.length };
}

module.exports = { listFolder, MAX_SKIPPED_SHOWN };
