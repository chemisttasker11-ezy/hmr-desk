// Starts the My Health Record / eMIMS helper in a hidden tab when an engine task waits for it, so queued runs
// need no open tab and no click. PPA stays manual: it only fills forms the pharmacist checks and submits.
const START = { emims: 'mims-run', mhr: 'hmr-run-start' };
const BACKOFF = 5 * 60 * 1000; // after a sign-in page or a missing button, wait before trying that tab again

module.exports = ({ api, armed, waitingTasks, ensureView, arm, notify, pageScript, now = Date.now }) => {
  const started = {},
    blocked = {},
    inFlight = {},
    retryPending = {},
    activeWaiting = {};
  async function loaded(view) {
    if (view.webContents.isLoading()) await new Promise((ok) => view.webContents.once('did-stop-loading', ok));
  }
  async function tick() {
    let tasks;
    try {
      tasks = (await api('GET', '/api/run')).tasks || [];
    } catch {
      return;
    }
    for (const site of Object.keys(START)) {
      activeWaiting[site] = tasks.some((t) => t.state === 'waiting' && t.waiting_for === site);
      if (started[site] && !(waitingTasks[site] || []).length) {
        armed[site] = false; // batch finished: free the tab for the next queued run
        started[site] = false;
      }
      if (armed[site] || inFlight[site] || (blocked[site] && now() - blocked[site] < BACKOFF)) continue;
      if (!activeWaiting[site]) continue;
      inFlight[site] = true;
      try {
        const view = ensureView(site);
        await loaded(view);
        await view.webContents.executeJavaScript(pageScript('check')); // throws on a sign-in page
        if ((await arm(site)) !== 'Ready') {
          inFlight[site] = false;
          continue;
        }
        const clicked = await view.webContents.executeJavaScript(
          `(() => { const b = document.getElementById(${JSON.stringify(START[site])}); if (!b || b.disabled) return false; b.click(); return true; })()`,
        );
        if (!clicked) throw Error(site === 'mhr' ? 'open the My Health Record search page once' : 'helper button not found');
        started[site] = true;
        blocked[site] = 0;
        inFlight[site] = false;
        notify('result', { site, status: 'Started in the background' });
      } catch (e) {
        inFlight[site] = false;
        armed[site] = false;
        blocked[site] = now();
        notify('result', {
          site,
          status: 'Background start paused: ' + (/sign-in page/i.test(e.message) ? 'sign-in needed' : e.message),
        });
      } finally {
        if (retryPending[site]) {
          delete retryPending[site];
          blocked[site] = 0;
          queueMicrotask(() => { void tick().catch(() => {}); });
        }
      }
    }
  }
  return {
    tick,
    hasWaiting: (site) => !!activeWaiting[site],
    start: (ms = 20000) => setInterval(tick, ms),
    retry(site) {
      if (site) {
        blocked[site] = 0;
        if (inFlight[site]) retryPending[site] = true;
      }
      return tick();
    },
  };
};
