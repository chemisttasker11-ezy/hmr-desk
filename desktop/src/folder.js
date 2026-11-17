const path = require('node:path');
function inside(base, target) {
  const relative = path.relative(base, target);
  return !!relative && relative !== '..' && !relative.startsWith('..' + path.sep) && !path.isAbsolute(relative);
}
module.exports = { inside };
