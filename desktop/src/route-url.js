module.exports = (value) => {
  if (typeof value !== 'string' || !value.startsWith('https://www.google.com/maps/dir/')) return false;
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && url.hostname === 'www.google.com' && !url.port && !url.username && !url.password && url.pathname.startsWith('/maps/dir/');
  } catch { return false; }
};
