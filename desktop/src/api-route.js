// A renderer-supplied API route must already be in canonical form. fetch() later
// normalises dot segments, so a blocklist that checks the raw string can be
// bypassed (/api/x/../records/export). Reject anything that is not canonical.
function isCanonicalApiRoute(value) {
  if (typeof value !== 'string' || !value.startsWith('/api/')) return false;
  if (/[\\\u0000-\u001f\u007f]/.test(value)) return false;
  let url;
  try { url = new URL(value, 'http://local'); } catch { return false; }
  if (url.origin !== 'http://local' || url.pathname + url.search !== value) return false;
  if (/\/\/|%2e|%2f|%5c|%00/i.test(url.pathname)) return false;
  return !url.pathname.split('/').some(segment => segment === '.' || segment === '..');
}
module.exports = { isCanonicalApiRoute };
