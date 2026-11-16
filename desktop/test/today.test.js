const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const H = require('../renderer/helpers');
const allowedRoute = require('../src/route-url');
function setup() {
  const calls = [], opened = [];
  const nodes = Object.fromEntries(['screen', 'calendar', 'day-content', 'period-bar', 'period-summary', 'appointment-editor', 'appointment-form', 'appointment-error', 'plan-editor', 'plan-form', 'plan-error', 'route-include', 'route-result', 'snapshot-status'].map((id) => [id, { innerHTML: '', textContent: '', querySelectorAll: () => [] }]));
  const appointments = [{ id: 7, date: '2026-11-12', start: '10:00', end: '11:00', title: 'Meeting', place: 'Office', note: 'Note' }];
  const context = vm.createContext({ esc: H.esc, date: H.date, page: 'calendar', formOpen: false, patients: [], confirm: () => true,
    FormData: class { constructor(form) { return form.values; } },
    localDate: (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`,
    $: (id) => nodes[id], errorText: (e) => e.message,
    hmr: { openRoute: async (url) => { if (!allowedRoute(url)) throw Error('Invalid route URL'); opened.push(url); }, api: async (method, path, body) => {
      calls.push({ method, path, body });
      if (path === '/api/today') return { alerts: [] };
      if (path === '/api/patients') return { patients: [] };
      if (path.startsWith('/api/summary?')) return { days: [{ date: '2026-11-12', total: 5, confirmed: 3, waiting: 1, declined: 1, hold: 0, not_sent: 0 }], totals: { total: 5, confirmed: 3, waiting: 1, declined: 1, hold: 0, not_sent: 0 } };
      if (path.startsWith('/api/days?')) return [{ date: '2026-11-12', total: 5, confirmed: 3, changed: 1 }];
      if (path.startsWith('/api/appointments?')) return appointments;
      if (method === 'POST') return {};
      if (path.includes('/route?')) return { urls: ['https://www.google.com/maps/dir/a/b'], skipped: [{ name: 'Alex', reason: 'No address' }] };
      return { plan: { start_time: '08:30', start_place: 'Home', end_place: 'Home', defaults: { start_time: true, start_place: true, end_place: true } }, summary: { total: 5, confirmed: 3 }, stops: [{ status: 'confirmed', names: ['Confirmed Patient'], time: '09:00', ll: [-27, 153] }, { status: 'offered', names: ['Offered Patient'], time: '09:30', ll: [-28, 153] }, { status: 'meeting', title: 'Meeting', time: '10:00', ll: [-27, 154] }] };
    } },
  });
  vm.runInContext(fs.readFileSync(require.resolve('../renderer/today.js'), 'utf8'), context);
  vm.runInContext("calendarMonth = new Date(2026, 10, 1); selectedDay = '2026-11-12'", context);
  const click = (node, dataset) => node.onclick({ target: { closest: () => ({ dataset }) } });
  return { context, nodes, calls, opened, click };
}
test('calendar renders period summary, totals and selection', async () => {
  const { context, nodes, calls, click } = setup(); await context.today();
  assert.match(nodes.calendar.innerHTML, /3\/5/); assert.match(nodes.calendar.innerHTML, /changed-dot/);
  assert.match(nodes['period-summary'].innerHTML, /Waiting/); assert.match(nodes['period-summary'].innerHTML, /<details class="summary-table">/); assert.match(nodes['period-summary'].innerHTML, /summary-total/);
  assert.match(context.snapshotText(), /Total\t5\t3\t1\t1\t0\t0/);
  await click(nodes['period-summary'], { summaryDay: '2026-11-13' });
  assert.ok(calls.some((c) => c.path === '/api/days/2026-11-13'));
  await click(nodes['period-bar'], { period: 'week' });
  assert.ok(calls.some((c) => c.path === '/api/summary?from=2026-11-09&to=2026-11-15'));
});
test('appointment add, edit and delete post the expected data', async () => {
  const { context, nodes, calls, click } = setup(); await context.today();
  assert.match(nodes['day-content'].innerHTML, /Meeting/);
  const values = Object.entries({ title: 'Meeting', date: '2026-11-12', start: '10:00', end: '11:00', place: 'Office', note: 'Note' });
  await click(nodes['day-content'], { addAppointment: '' });
  await nodes['appointment-form'].onsubmit({ preventDefault() {}, target: { values } });
  await click(nodes['day-content'], { editAppointment: '7' });
  await nodes['appointment-form'].onsubmit({ preventDefault() {}, target: { values } });
  await click(nodes['day-content'], { deleteAppointment: '7' });
  const posts = calls.filter((c) => c.method === 'POST');
  assert.equal(posts[0].path, '/api/appointments'); assert.equal(posts[0].body.title, 'Meeting');
  assert.equal(posts[1].body.id, 7); assert.equal(posts[2].path, '/api/appointments/7/delete');
});
test('route opens Google directions and reports skipped stops', async () => {
  const { context, nodes, calls, opened, click } = setup(); await context.today();
  await click(nodes['day-content'], { openRoute: '' });
  assert.ok(calls.some((c) => c.path.endsWith('route?include=confirmed')));
  await click(nodes['day-content'], { routeInclude: 'all' });
  await click(nodes['day-content'], { openRoute: '' });
  assert.deepEqual(opened, ['https://www.google.com/maps/dir/a/b', 'https://www.google.com/maps/dir/a/b']);
  assert.ok(calls.some((c) => c.path === '/api/days/2026-11-12/route?include=all'));
  assert.match(nodes['route-result'].innerHTML, /Alex: No address/);
  for (const url of ['https://www.google.com/maps/dir/a', 'https://www.google.com/maps/dir/?api=1']) assert.equal(allowedRoute(url), true);
  for (const url of ['http://www.google.com/maps/dir/a', 'https://www.google.com.evil.test/maps/dir/a', 'https://www.google.com/maps/dir/../search', 'https://evil.test/']) assert.equal(allowedRoute(url), false);
});
test('stop switch keeps the list, map and route selection together', async () => {
  const { context, nodes, calls, click } = setup();
  vm.runInContext('renderDayMap = (data) => { globalThis.mappedStops = data.stops; }', context);
  await context.today();
  assert.match(nodes['day-content'].innerHTML, /Confirmed Patient/);
  assert.doesNotMatch(nodes['day-content'].innerHTML, /Offered Patient/);
  assert.deepEqual(Array.from(context.mappedStops, (s) => s.status), ['confirmed', 'meeting']);
  assert.match(nodes['day-content'].innerHTML, /Meeting/);
  await click(nodes['day-content'], { routeInclude: 'all' });
  assert.match(nodes['day-content'].innerHTML, /Offered Patient/);
  assert.deepEqual(Array.from(context.mappedStops, (s) => s.status), ['confirmed', 'offered', 'meeting']);
  assert.equal((nodes['day-content'].innerHTML.match(/<details class="stop-row" name="day-stops">/g) || []).length, 2);
  await context.loadDay('2026-11-13');
  await click(nodes['day-content'], { openRoute: '' });
  assert.ok(calls.some((c) => c.path.endsWith('/2026-11-13/route?include=all')));
});
test('stop rows open the matching patient, preferring a same-day visit', async () => {
  const { context, nodes } = setup();
  vm.runInContext("renderDayMap = () => {}; patients = [{ id: 3, name: 'Confirmed Patient', visit_date: '2026-10-01' }, { id: 4, name: 'Confirmed Patient', visit_date: '2026-11-12' }]", context);
  await context.loadDay('2026-11-12');
  assert.match(nodes['day-content'].innerHTML, /<button data-drawer-patient="4">Open patient<\/button>/);
  assert.match(nodes['day-content'].innerHTML, /<strong class="stop-link" data-drawer-patient="4"/);
  assert.equal((nodes['day-content'].innerHTML.match(/data-drawer-patient/g) || []).length, 2);
});
test('rail separates today and calendar', () => {
  const source = fs.readFileSync(require.resolve('../renderer.js'), 'utf8');
  assert.match(source, /today: 'Today'/); assert.match(source, /calendar: 'Calendar'/); assert.match(source, /id = 'calendar'/);
});

test('numbers visits and meetings in time order', async () => {
  const { context, nodes, click } = setup(); await context.today();
  assert.match(nodes['day-content'].innerHTML, /data-stop="0"><span class="stop-number"[^>]*>1<\/span>/);
  assert.match(nodes['day-content'].innerHTML, /appointment-badge">2<\/span>/);
  await click(nodes['day-content'], { routeInclude: 'all' });
  assert.match(nodes['day-content'].innerHTML, /appointment-badge">3<\/span>/);
});
test('day plan shows defaults and saves or resets the requested fields', async () => {
  const { context, nodes, calls, click } = setup(); await context.today();
  assert.match(nodes['day-content'].innerHTML, /Start 08:30<\/strong> <small>\(default\)<\/small> from Home/);
  await click(nodes['day-content'], { editPlan: 'start' });
  assert.match(nodes['plan-editor'].innerHTML, /type="time" name="start_time"/);
  await nodes['plan-form'].onsubmit({ preventDefault() {}, target: { values: [['start_time', '09:00'], ['start_place', 'Office']] } });
  const post = calls.find((c) => c.path.endsWith('/plan') && c.method === 'POST');
  assert.equal(JSON.stringify(post.body), JSON.stringify({ start_time: '09:00', start_place: 'Office' }));
  await click(nodes['day-content'], { defaultPlan: 'end' });
  assert.equal(JSON.stringify(calls.filter((c) => c.method === 'POST').at(-1).body), JSON.stringify({ end_place: '' }));
});
test('settings render time fields as time inputs', () => {
  const context = vm.createContext({ esc: H.esc });
  vm.runInContext(fs.readFileSync(require.resolve('../renderer/settings.js'), 'utf8'), context);
  vm.runInContext("practiceSettings = [{ key: 'day_start_time', label: 'Day start time', type: 'time', value: '08:30', default: '08:30' }]", context);
  assert.match(context.practiceFields(), /data-setting="day_start_time" type="time"/);
});
