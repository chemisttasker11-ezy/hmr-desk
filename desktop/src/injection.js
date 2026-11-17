const fs = require('node:fs');
function matches(url, patterns) {
  let u;
  try {
    u = new URL(url);
  } catch {
    return false;
  }
  return patterns.some((pattern) => {
    const m = /^(\*|https?|file):\/\/([^/]*)(\/.*)$/.exec(pattern);
    if (!m) return false;
    const host = m[2].toLowerCase(),
      actual = u.hostname.toLowerCase();
    if (!(m[1] === '*' ? ['http:', 'https:'].includes(u.protocol) : u.protocol === m[1] + ':')) return false;
    if (!(
      host === '*' ||
      (host.startsWith('*.') ? actual === host.slice(2) || actual.endsWith('.' + host.slice(2)) : actual === host)
    ))
      return false;
    const re = new RegExp(
      '^' +
        m[3]
          .split('*')
          .map((s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
          .join('.*') +
        '$',
    );
    return re.test(u.pathname + u.search);
  });
}
function patterns(manifest) {
  return JSON.parse(fs.readFileSync(manifest, 'utf8')).content_scripts.flatMap((x) => x.matches);
}
function assemble(name, data, source, runToken) {
  if (name === 'MIMS_LISTS') {
    const replaceOnce = (from, to) => {
      if (source.indexOf(from) < 0 || source.indexOf(from) !== source.lastIndexOf(from)) throw Error('Unsupported MIMS helper version');
      source = source.replace(from, to);
    };
    replaceOnce("const sleep = ms => new Promise(r => setTimeout(r, ms));", "const sleep = ms => new Promise(r => setTimeout(r, ms)).then(() => checkRun());");
    replaceOnce("async function add(input, name) {", "async function add(input, name) { checkRun();");
    replaceOnce("async function details() {", "async function details() { checkRun();");
    replaceOnce("async function runOne(list) {", "async function runOne(list) { checkRun();");
    replaceOnce("for (const [i, list] of MIMS_LISTS.entries()) {", "for (const [i, list] of MIMS_LISTS.entries()) { if (!isCurrent()) break;");
    replaceOnce("const b = document.createElement('button');", "const b = document.createElement('button'); b.id = 'mims-run';");
    source = `const token = ${JSON.stringify(runToken || '')};
` +
      "window.__hmrMimsRun = token; document.getElementById('mims-run')?.remove();\n" +
      "const isCurrent = () => window.__hmrMimsRun === token;\n" +
      "const checkRun = () => { if (!isCurrent()) throw Error('MIMS helper stopped'); };\n" + source;
  }
  if (name === 'PPA_CLAIMS') {
    source = source.replaceAll('pch-fill', 'ppa-fill');
    source = source.replace(
      'const missing = fill(c);',
      'const missing = fill(c); chrome.runtime.sendMessage({type: "filled", ' +
        'index: +box.querySelector("#pch-pick").value});',
    );
    for (const field of ['given', 'family', 'interview']) {
      source = source.replace('${c.' + field + '}', '${escapeText(c.' + field + ')}');
    }
    source =
      `const escapeText = s => String(s ?? '').replace(/[&<>"']/g, c =>
      ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'})[c]);\n` + source;
  }
  const bridge = name === 'MIMS_LISTS' ? 'message => window.hmrBridge.sendMessage({...message, hmrRun: token})' : 'message => window.hmrBridge.sendMessage(message)';
  return `{\nconst chrome = {runtime: {sendMessage: ${bridge}}};\nconst ${name} = ${JSON.stringify(data).replace(/</g, '\\u003c')};\n${source}\n}`;
}
module.exports = { matches, patterns, assemble };
