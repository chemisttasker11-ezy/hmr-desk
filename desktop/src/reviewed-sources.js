'use strict';
/** Renderer never submits filesystem paths for reviewed-document opening. */
const fs = require('node:fs/promises');
const path = require('node:path');
const crypto = require('node:crypto');

class ReviewedSources {
  constructor({ now = () => Date.now(), ttl = 30 * 60 * 1000 } = {}) {
    this.now = now;
    this.ttl = ttl;
    this.records = new Map();
  }
  remember(paths, response) {
    if (!Array.isArray(paths) || !Array.isArray(response?.rows)) return;
    response.rows.forEach((row, i) => {
      if (/^[a-f0-9]{32}$/.test(row?.token || '') &&
          /^[a-f0-9]{64}$/.test(row?.sha256 || '') && path.isAbsolute(paths[i] || '')) {
        this.records.set(row.token, { file: paths[i], hash: row.sha256, timestamp: this.now() });
      }
    });
    for (const [token, item] of this.records) {
      if (this.now() - item.timestamp > this.ttl) this.records.delete(token);
    }
  }
  async verifiedPath(token) {
    if (typeof token !== 'string' || !/^[a-f0-9]{32}$/.test(token)) throw Error('Invalid referral review token');
    const entry = this.records.get(token);
    if (!entry || this.now() - entry.timestamp > this.ttl) {
      this.records.delete(token);
      throw Error('Referral review expired; choose the PDF again');
    }
    const stat = await fs.lstat(entry.file);
    if (!stat.isFile() || stat.isSymbolicLink() || path.extname(entry.file).toLowerCase() !== '.pdf' ||
        stat.size > 25 * 1024 * 1024 || stat.size < 5) throw Error('Invalid source PDF');
    const bytes = await fs.readFile(entry.file);
    if (crypto.createHash('sha256').update(bytes).digest('hex') !== entry.hash)
      throw Error('Original referral changed; please review the new version');
    if (!bytes.subarray(0, 5).equals(Buffer.from('%PDF-'))) throw Error('Invalid PDF header');
    return entry.file;
  }
}
module.exports = { ReviewedSources };
