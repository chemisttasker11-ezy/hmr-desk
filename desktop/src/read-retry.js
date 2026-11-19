// A read-only GET that fails because the local engine closed the socket before sending any reply is retried once.
// Never used for POST: a write whose outcome is unknown must not be sent twice.
const RETRYABLE = new Set(['UND_ERR_SOCKET', 'ECONNRESET', 'EPIPE']);

function isDroppedSocket(error) {
  const code = error && (error.cause?.code || error.code);
  return RETRYABLE.has(code);
}

async function fetchWithReadRetry(fetchFn, method, url, options, delayMs = 150) {
  try {
    return await fetchFn(url, options);
  } catch (error) {
    if (method !== 'GET' || !isDroppedSocket(error)) throw error;
    await new Promise((resolve) => setTimeout(resolve, delayMs));
    return fetchFn(url, options);
  }
}

module.exports = { fetchWithReadRetry, isDroppedSocket };
