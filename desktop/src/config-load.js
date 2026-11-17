'use strict';
/** Validate stored app configuration without destroying old patient settings. */
const fs = require('node:fs');
const path = require('node:path');

function loadConfig(file, defaults) {
  if (!fs.existsSync(file)) return {config:{...defaults}, firstRun:true, recovery:''};
  try {
    const info = fs.lstatSync(file);
    if (!info.isFile() || info.isSymbolicLink()) throw Error('Unsupported configuration file');
    const stored = JSON.parse(fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, ''));
    if (!stored || typeof stored !== 'object' || Array.isArray(stored) ||
        typeof stored.base !== 'string' || !path.isAbsolute(stored.base) ||
        (stored.api !== undefined && typeof stored.api !== 'string') ||
        (stored.tokenFile !== undefined && typeof stored.tokenFile !== 'string')) {
      throw Error('Configuration does not contain a valid patient workspace');
    }
    return {config:{...defaults,...stored},firstRun:false,recovery:''};
  } catch (error) {
    // Keep broken config available for support; never silently delete an old
    // patient workspace or change its path to a guessed OneDrive location.
    const backup = file + '.invalid-' + Date.now();
    fs.renameSync(file, backup);
    return {config:{...defaults},firstRun:true,
      recovery:'Previous configuration was preserved for recovery. Choose your existing patient workspace or a new local folder explicitly.'};
  }
}
module.exports = {loadConfig};
