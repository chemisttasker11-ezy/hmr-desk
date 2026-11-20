function nextButton(p) {
  if (!p.next_step) return '';
  if (['wait for reply', 'visit', 'offer a time'].includes(String(p.next_step).toLowerCase())) {
    return `<span class="muted nowrap">${esc(p.next_step)}</span>`;
  }
  return `<button data-next="${esc(p.id)}" data-step="${esc(p.next_step)}">${esc(H.stepLabel(p.next_step))}</button>`;
}
function confirmed(p) {
  return ['confirmed', 'pathology_ready', 'sheet_ready'].includes(p.state);
}
function visitCards(rows) {
  rows.sort(
    (a, b) =>
      String(a.visit_time || '').localeCompare(String(b.visit_time || '')) ||
      Number(confirmed(b)) - Number(confirmed(a)),
  );
  return (
    rows
      .map(
        (p) => `<article class="card visit ${confirmed(p) ? '' : 'unconfirmed'}">
    <div class="time">${esc(p.visit_time || 'Time not set')}</div><div><strong>${esc(p.name)}</strong>
    <span class="visit-status">${confirmed(p) ? 'Confirmed' : 'Offered - not confirmed'}</span>
    <div>${esc(H.displayAddress(p.address, p.suburb))}</div><div>${esc(p.phone || '')}</div><div>${esc(p.note || '')}</div>
    ${nextButton(p)}</div></article>`,
      )
      .join('') || '<p class="muted">No visits planned.</p>'
  );
}
function alertDescription(a) {
  if (a.type.startsWith('follow-up'))
    return [a.date ? `Due ${date(a.date)}` : '', a.window_end ? `Window ends ${date(a.window_end)}` : '']
      .filter(Boolean)
      .join(' - ');
  if (a.type === 'new HMR possible') return a.date ? `From ${date(a.date)}` : '';
  if (!a.type.startsWith('referral')) return a.date ? date(a.date) : '';
  const days = Number(a.days_left);
  const remaining = Number.isFinite(days) ? (days < 0 ? `expired ${-days} days ago` : `${days} days left`) : '';
  return [date(a.date), remaining].filter(Boolean).join(' - ');
}
let selectedDay = null;
let calendarMonth = new Date(new Date().getFullYear(), new Date().getMonth(), 1);
let dayMap = null;
let dayRequest = 0;
let routeInclude = 'confirmed';

function calendarHtml(month, days, selected) {
  const year = month.getFullYear(), m = month.getMonth();
  const counts = new Map(days.map((d) => [d.date, d]));
  const first = new Date(year, m, 1).getDay();
  const length = new Date(year, m + 1, 0).getDate();
  const todayDate = localDate(new Date());
  let cells = '<span></span>'.repeat(first);
  for (let n = 1; n <= length; n++) {
    const d = localDate(new Date(year, m, n)), entry = counts.get(d);
    cells += `<button class="calendar-day ${d === todayDate ? 'is-today' : ''} ${d === selected ? 'is-selected' : ''}" data-day="${d}" aria-pressed="${d === selected}" aria-label="${esc(date(d))}${entry ? `, ${entry.confirmed} of ${entry.total} confirmed${entry.changed ? ', changed' : ''}` : ''}"><span>${n}${entry?.changed ? ' <i class="changed-dot" title="Changed"></i>' : ''}</span>${entry?.total ? `<small class="count-pill ${entry.confirmed === entry.total ? 'all-confirmed' : ''}">${esc(entry.confirmed)}/${esc(entry.total)}</small>` : ''}</button>`;
  }
  return `<div class="calendar-heading"><button data-month="-1" aria-label="Previous month">&lsaquo;</button><h2>${esc(month.toLocaleDateString('en-AU', { month: 'long', year: 'numeric' }))}</h2><button data-month="1" aria-label="Next month">&rsaquo;</button></div><div class="calendar-grid">${['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].map((d) => `<strong>${d}</strong>`).join('')}${cells}</div>`;
}
function stopColour(status) {
  const s = String(status || '').toLowerCase();
  if (s.includes('declin')) return '#626873';
  if (s.includes('chang') || s.includes('hold')) return '#875000';
  if (s.includes('confirm') || s.includes('schedul') || ['pathology_ready', 'sheet_ready'].includes(s)) return '#176b3a';
  if (s.includes('offer')) return '#2457ad';
  return '#555';
}
function daySummary(summary) {
  const s = summary || {};
  const areas = Array.isArray(s.suburbs) ? s.suburbs.join(', ') : (s.suburbs || '');
  return [`${esc(s.total || 0)} visit${Number(s.total) === 1 ? '' : 's'}`, `${esc(s.confirmed || 0)} confirmed`, s.first && s.last ? `${esc(s.first)}&ndash;${esc(s.last)}` : esc(s.first || s.last || ''), esc(areas)].filter(Boolean).join(' &middot; ');
}
function stopNames(stop) { return Array.isArray(stop.names) ? stop.names.join(', ') : (stop.names || stop.title || ''); }
function stopPatients(stop, day) {
  const names = Array.isArray(stop.names) ? stop.names : [stop.names || ''];
  // the engine sends patient_ids in the same order as names; name matching is only a fallback (e.g. mock data)
  if (Array.isArray(stop.patient_ids) && stop.patient_ids.length === names.length) return names.map((name, i) => ({ name, id: stop.patient_ids[i] }));
  return names.map((name) => {
    const matches = patients.filter((p) => p.name === name);
    return { name, id: (matches.find((p) => p.visit_date === day) || matches[0])?.id };
  }).filter((p) => p.id != null);
}
function stopOpenButtons(stop, day) {
  const list = stopPatients(stop, day);
  return list.length ? `<div class="actions stop-open">${list.map((p) => `<button data-drawer-patient="${esc(p.id)}">Open ${list.length > 1 ? esc(p.name) : 'patient'}</button>`).join('')}</div>` : '';
}
function stopNameHtml(stop, day) {
  const list = stopPatients(stop, day);
  return list.length === 1 && stopNames(stop) === list[0].name ? `<strong class="stop-link" data-drawer-patient="${esc(list[0].id)}" title="Open patient">${esc(list[0].name)}</strong>` : `<strong>${esc(stopNames(stop))}</strong>`;
}
function hasPosition(ll) { return Array.isArray(ll) && ll.length === 2 && ll.every((n) => typeof n === 'number' && Number.isFinite(n)); }
let highlightedStopPatient = '', highlightedStops = [];
function renderDayMap(data) {
  highlightedStopPatient = ''; highlightedStops = data.stops || [];
  if (dayMap) { dayMap.remove(); dayMap = null; }
  if (typeof L === 'undefined' || !$('day-map')) return;
  const map = L.map('day-map'); dayMap = map;
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution: '&copy; OpenStreetMap contributors' }).addTo(map);
  const points = [], markers = [];
  if (hasPosition(data.home?.ll)) {
    points.push(data.home.ll);
    L.marker(data.home.ll, { icon: L.divIcon({ className: '', html: '<span class="map-home">H</span>', iconSize: [26, 26] }) }).addTo(map).bindPopup(esc(data.home.name || 'Home'));
  }
  data.stops.forEach((s, i) => {
    if (!hasPosition(s.ll)) return;
    points.push(s.ll);
    const icon = L.divIcon({ className: '', html: s.status === 'meeting' ? `<span class="map-pin appointment-badge">${data.numbers[i] || i + 1}</span>` : `<span class="map-pin" style="background:${stopColour(s.status)}">${data.numbers[i] || i + 1}</span>`, iconSize: [26, 26] });
    const marker = L.marker(s.ll, { icon }).addTo(map).bindPopup(`<strong>${esc(stopNames(s))}</strong><br>${esc(s.time || '')} &middot; ${esc(s.status_text || s.status || '')}`);
    marker.on('click', () => highlightStop(i, markers));
    markers[i] = marker;
  });
  if (hasPosition(data.home?.ll) && points.length > 1) L.polyline([...points, data.home.ll], { color: '#2457ad', weight: 3, opacity: .7, dashArray: '6 6' }).addTo(map);
  if (points.length > 1) map.fitBounds(L.latLngBounds(points).pad(.15));
  else map.setView(points[0] || [-27.95, 153.35], 11);
  $('day-list').onclick = (event) => {
    const row = event.target.closest('[data-stop]');
    if (row) highlightStop(Number(row.dataset.stop), markers);
  };
}
function highlightStop(i, markers) {
  const stopPatientList = highlightedStops[i] ? stopPatients(highlightedStops[i], selectedDay) : [];
  highlightedStopPatient = stopPatientList.length === 1 && stopPatientList[0].id != null ? String(stopPatientList[0].id) : '';
  document.querySelectorAll('[data-stop]').forEach((row) => row.classList.toggle('stop-selected', Number(row.dataset.stop) === i));
  if (markers[i]) { markers[i].openPopup(); dayMap.panTo(markers[i].getLatLng()); }
}
async function loadDay(day) {
  const request = ++dayRequest;
  selectedDay = day;
  const [data, appointmentReply] = await Promise.all([
    hmr.api('GET', `/api/days/${day}`),
    hmr.api('GET', `/api/appointments?from=${day}&to=${day}`),
  ]);
  if (request !== dayRequest || page !== 'calendar' || !$('day-content')) return;
  const appointments = Array.isArray(appointmentReply) ? appointmentReply : appointmentReply?.appointments || []; // engine wraps the list
  const stops = (data.stops || []).filter((s) => routeInclude === 'all' || s.status === 'meeting' || ['confirmed', 'pathology_ready', 'sheet_ready'].includes(String(s.status || '').toLowerCase()));
  const entries = [
    ...stops.map((stop, index) => ({ stop, index })).filter(({ stop }) => stop.status !== 'meeting'),
    ...appointments.map((appointment) => ({ appointment })),
  ].sort((a, b) => String(a.appointment?.start || a.stop?.time || '99').localeCompare(String(b.appointment?.start || b.stop?.time || '99')));
  const numbers = stops.map((s) => entries.findIndex((entry) => entry.stop === s || (s.status === 'meeting' && entry.appointment && (s.id != null ? String(entry.appointment.id) === String(s.id) : entry.appointment.start === s.time && entry.appointment.title === s.title))) + 1);
  const plan = data.plan || { defaults: {} };
  const headingDate = new Date(`${day}T12:00:00`).toLocaleDateString('en-AU', { weekday: 'short', day: 'numeric', month: 'short' });
  $('day-content').innerHTML = `<h2 class="day-heading">${esc(headingDate)}</h2><p class="day-summary">${daySummary(data.summary)}</p>
    <div class="day-actions"><div class="route-switch" role="group" aria-label="Show stops">${[['confirmed', 'Confirmed'], ['all', 'All']].map(([value, label]) => `<button data-route-include="${value}" aria-pressed="${routeInclude === value}" class="${routeInclude === value ? 'active' : ''}">${label}</button>`).join('')}</div><button data-add-appointment>Add meeting</button><button class="primary" data-open-route>Open route in Google Maps</button></div><div id="route-result" role="status"></div><div id="appointment-editor"></div>
    <section class="day-plan" aria-label="Day plan"><div><strong>Start ${esc(plan.start_time || 'Time not set')}</strong>${plan.defaults?.start_time ? ' <small>(default)</small>' : ''} from ${esc(plan.start_place || 'Not set')}${plan.defaults?.start_place ? ' <small>(default)</small>' : ''} <button data-edit-plan="start">Edit start</button></div><div><strong>End at</strong> ${esc(plan.end_place || 'Not set')}${plan.defaults?.end_place ? ' <small>(default)</small>' : ''} <button data-edit-plan="end">Edit end</button></div><div id="plan-editor"></div></section>
    <div id="day-list">${entries.map(({ stop: s, index: i, appointment: a }, order) => a ? `<article class="appointment-row"><span class="stop-number appointment-badge">${order + 1}</span><span class="stop-time">${esc(a.start || 'Time not set')}${a.end ? `<small>to ${esc(a.end)}</small>` : ''}</span><span class="stop-name"><strong>${esc(a.title)}</strong>${a.place ? ` <span class="muted">${esc(a.place)}</span>` : ''}${a.note ? `<small>${esc(a.note)}</small>` : ''}</span><span class="row-actions"><button data-edit-appointment="${esc(a.id)}">Edit</button><button data-delete-appointment="${esc(a.id)}">Delete</button></span></article>` : `<details class="stop-row" name="day-stops"><summary data-stop="${i}"><span class="stop-number" style="background:${stopColour(s.status)}">${order + 1}</span><span class="stop-time">${esc(s.time || 'Time not set')}</span><span class="stop-name">${stopNameHtml(s, day)}<span class="status-chip" style="--status-color:${stopColour(s.status)}">${esc(s.status_text || s.status || '')}</span></span><span class="muted">${esc(s.suburb || '')}</span><span class="chevron" aria-hidden="true"></span></summary><div class="stop-details">${s.address ? `<div>${esc(s.address)}</div>` : ''}${s.phone ? `<div><a href="tel:${esc(String(s.phone).replace(/[^\d+]/g, ''))}">${esc(s.phone)}</a></div>` : ''}${s.note ? `<div>${esc(s.note)}</div>` : ''}${s.address || s.phone || s.note ? '' : '<div class="muted">No address, phone or note saved.</div>'}${stopOpenButtons(s, day)}</div></details>`).join('') || '<p class="muted">No visits or meetings planned.</p>'}</div>    <div id="day-map" aria-label="Day route map"></div><div class="map-legend">${[['#176b3a', 'Confirmed'], ['#2457ad', 'Offered'], ['#875000', 'Changed'], ['#626873', 'Declined'], ['#dce1e4', 'Meeting']].map(([c, label]) => `<span><i style="background:${c}"></i>${label}</span>`).join('')}</div><p class="muted map-note">Pins sit at suburb centres, not street addresses${stops.some((s) => !hasPosition(s.ll)) ? ` &middot; Stops without a map position: ${stops.map((s, i) => !hasPosition(s.ll) ? `${numbers[i] || i + 1}. ${esc(stopNames(s) || s.suburb || 'Unknown')}` : '').filter(Boolean).join(', ')}` : ''}</p>
`;
  $('day-content').onclick = async (event) => {
    const button = event.target.closest('button');
    if (!button) return;
    try {
      if (button.dataset.routeInclude) { routeInclude = button.dataset.routeInclude; await loadDay(day); }
      else if (button.dataset.editPlan) {
        const start = button.dataset.editPlan === 'start';
        $('plan-editor').innerHTML = `<form id="plan-form"><div class="form">${start ? `<label>Start time<input type="time" name="start_time" value="${esc(plan.start_time || '')}" required></label><label>Start location<input name="start_place" maxlength="200" value="${esc(plan.start_place || '')}"></label>` : `<label>End point<input name="end_place" maxlength="200" value="${esc(plan.end_place || '')}"></label>`}</div><p id="plan-error" class="error" role="alert"></p><button class="primary" type="submit">Save</button> <button type="button" data-default-plan="${start ? 'start' : 'end'}">Use default</button> <button type="button" data-cancel-plan>Cancel</button></form>`;
        $('plan-form').onsubmit = async (e) => {
          e.preventDefault();
          try { await saveDayPlan(day, Object.fromEntries(new FormData(e.target))); }
          catch (error) { $('plan-error').textContent = errorText(error); }
        };
      } else if (button.dataset.defaultPlan) {
        await saveDayPlan(day, button.dataset.defaultPlan === 'start' ? { start_time: '', start_place: '' } : { end_place: '' });
      } else if ('cancelPlan' in button.dataset) $('plan-editor').innerHTML = '';
      else if ('addAppointment' in button.dataset || 'editAppointment' in button.dataset) {
        const a = appointments.find((item) => String(item.id) === button.dataset.editAppointment) || { date: day };
        $('appointment-editor').innerHTML = `<form id="appointment-form" class="card"><h3>${a.id == null ? 'Add' : 'Edit'} meeting</h3><div class="form">${[['title','Description','text'], ['date','Date','date'], ['start','Start','time'], ['end','End','time'], ['place','Place','text'], ['note','Note','text']].map(([key,label,type]) => `<label>${label}<input name="${key}" type="${type}" value="${esc(a[key] || '')}" ${['title','date','start','end'].includes(key) ? 'required' : ''}></label>`).join('')}</div><p id="appointment-error" class="error" role="alert"></p><button class="primary" type="submit">Save meeting</button> <button type="button" data-cancel-appointment>Cancel</button></form>`;
        $('appointment-form').onsubmit = async (e) => {
          e.preventDefault();
          const values = Object.fromEntries(new FormData(e.target));
          if (values.end <= values.start) { $('appointment-error').textContent = 'End time must be after start time.'; return; }
          try {
            await hmr.api('POST', '/api/appointments', { ...values, ...(a.id == null ? {} : { id: a.id }) });
            await Promise.all([loadDay(day), loadCalendar(), loadSummary()]);
          } catch (error) { $('appointment-error').textContent = errorText(error); }
        };
      } else if ('cancelAppointment' in button.dataset) $('appointment-editor').innerHTML = '';
      else if ('deleteAppointment' in button.dataset) {
        if (!confirm('Delete this meeting?')) return;
        await hmr.api('POST', `/api/appointments/${encodeURIComponent(button.dataset.deleteAppointment)}/delete`);
        await Promise.all([loadDay(day), loadCalendar(), loadSummary()]);
      } else if ('openRoute' in button.dataset) {
        button.disabled = true;
        try {
          const route = await hmr.api('GET', `/api/days/${day}/route?include=${routeInclude}`);
          $('route-result').innerHTML = (route.skipped || []).length ? `<p><strong>Skipped stops:</strong></p><ul>${route.skipped.map((s) => `<li>${esc(s.name)}: ${esc(s.reason)}</li>`).join('')}</ul>` : '<p>No stops skipped.</p>';
          for (const url of route.urls || []) await hmr.openRoute(url);
          if (!(route.urls || []).length) $('route-result').innerHTML += '<p>No route available for this day.</p>';
        } finally { button.disabled = false; }
      }
    } catch (error) { $('route-result').innerHTML = `<p class="error">${esc(errorText(error))}</p>`; }
  };
  renderDayMap({ ...data, stops, numbers });
}
async function saveDayPlan(day, values) {
  await hmr.api('POST', `/api/days/${day}/plan`, values);
  await loadDay(day);
}
let period = 'month';
let customFrom = '', customTo = '';
let summaryRequest = 0;
const summaryColumns = [['total', 'Visits'], ['confirmed', 'Confirmed'], ['waiting', 'Waiting'], ['declined', 'Declined'], ['hold', 'On hold'], ['not_sent', 'Not sent']];
function periodRange() {
  const d = new Date(`${selectedDay}T12:00:00`);
  if (period === 'custom') return [customFrom, customTo];
  if (period === 'day') return [selectedDay, selectedDay];
  if (period === 'week') {
    const start = new Date(d); start.setDate(d.getDate() - (d.getDay() + 6) % 7);
    const end = new Date(start); end.setDate(start.getDate() + 6);
    return [localDate(start), localDate(end)];
  }
  return [localDate(new Date(d.getFullYear(), d.getMonth(), 1)), localDate(new Date(d.getFullYear(), d.getMonth() + 1, 0))];
}
function renderPeriodBar() {
  customFrom ||= selectedDay; customTo ||= selectedDay;
  $('period-bar').innerHTML = `<div class="period-bar"><div class="chips" role="group" aria-label="Summary period">${['day','week','month','custom'].map((p) => `<button data-period="${p}" class="${period === p ? 'active' : ''}" aria-pressed="${period === p}">${p[0].toUpperCase() + p.slice(1)}</button>`).join('')}</div>${period === 'custom' ? `<label>From <input id="period-from" type="date" value="${esc(customFrom)}"></label><label>To <input id="period-to" type="date" value="${esc(customTo)}"></label><button data-apply-period>Apply</button>` : ''}<button data-copy-snapshot>Copy snapshot</button><span id="snapshot-status" role="status"></span></div>`;
  $('period-bar').onclick = async (event) => {
    const button = event.target.closest('button'); if (!button) return;
    try {
      if (button.dataset.period) { period = button.dataset.period; renderPeriodBar(); await loadSummary(); }
      else if ('applyPeriod' in button.dataset) {
        const from = $('period-from').value, to = $('period-to').value;
        if (!from || !to || from > to) { $('snapshot-status').textContent = 'Choose a valid date range.'; return; }
        customFrom = from; customTo = to; await loadSummary();
      } else if ('copySnapshot' in button.dataset) {
        await navigator.clipboard.writeText(snapshotText()); $('snapshot-status').textContent = 'Snapshot copied.';
      }
    } catch (error) { $('snapshot-status').textContent = errorText(error); }
  };
}
let currentSummary = { days: [], totals: {} };
function snapshotText() {
  const [from, to] = periodRange();
  const values = (row) => summaryColumns.map(([key]) => row[key] ?? 0);
  return [`Workload summary: ${from} to ${to}`, ['Date', ...summaryColumns.map(([, label]) => label)].join('\t'), ...currentSummary.days.map((row) => [row.date, ...values(row)].join('\t')), ['Total', ...values(currentSummary.totals)].join('\t')].join('\n');
}
async function loadSummary() {
  const request = ++summaryRequest, [from, to] = periodRange();
  const result = await hmr.api('GET', `/api/summary?from=${from}&to=${to}`);
  if (request !== summaryRequest || page !== 'calendar' || !$('period-summary')) return;
  currentSummary = result;
  const cells = (row) => summaryColumns.map(([key]) => `<td>${esc(row[key] ?? 0)}</td>`).join('');
  $('period-summary').innerHTML = `<div class="summary-chips" aria-label="Period totals">${summaryColumns.filter(([key]) => Number(result.totals?.[key] || 0) !== 0).map(([key, label]) => `<span class="summary-chip summary-${key}"><small>${label}</small><strong>${esc(result.totals?.[key] ?? 0)}</strong></span>`).join('')}</div><details class="summary-table"><summary>Show table</summary><div class="summary-scroll"><table><thead><tr><th scope="col">Date</th>${summaryColumns.map(([, label]) => `<th scope="col">${label}</th>`).join('')}</tr></thead><tbody>${result.days.map((row) => `<tr><th scope="row"><a href="#" data-summary-day="${esc(row.date)}">${esc(date(row.date))}</a></th>${cells(row)}</tr>`).join('')}<tr class="summary-total"><th scope="row">Total</th>${cells(result.totals || {})}</tr></tbody></table></div></details>`;
  $('period-summary').onclick = async (event) => {
    const button = event.target.closest('[data-summary-day]'); if (!button) return;
    event.preventDefault?.();
    try {
      selectedDay = button.dataset.summaryDay;
      const d = new Date(`${selectedDay}T12:00:00`); calendarMonth = new Date(d.getFullYear(), d.getMonth(), 1);
      await Promise.all([loadCalendar(), loadDay(selectedDay)]);
    } catch (error) { $('day-content').innerHTML = `<p class="error">${esc(errorText(error))}</p>`; }
  };
}
async function loadCalendar() {
  const first = localDate(new Date(calendarMonth.getFullYear(), calendarMonth.getMonth(), 1));
  const last = localDate(new Date(calendarMonth.getFullYear(), calendarMonth.getMonth() + 1, 0));
  const days = await hmr.api('GET', `/api/days?from=${first}&to=${last}`);
  if (page === 'calendar' && $('calendar')) $('calendar').innerHTML = calendarHtml(calendarMonth, days, selectedDay);
}
async function today() {
  selectedDay ||= localDate(new Date());
  if (dayMap) { dayMap.remove(); dayMap = null; }
  const list = await hmr.api('GET', '/api/patients');
  if (page !== 'calendar' || formOpen) return;
  patients = list.patients;
  $('screen').innerHTML = `<div class="period-row"><section id="period-bar"></section><section id="period-summary" aria-live="polite"></section></div><div class="today-layout"><section id="day-content" aria-live="polite"></section><section id="calendar" aria-label="Visit calendar"></section></div><div id="detail" class="detail drawer" role="dialog" aria-label="Patient" hidden></div>`;
  $('calendar').onclick = async (event) => {
    const button = event.target.closest('button');
    if (!button) return;
    try {
      if (button.dataset.month) {
        calendarMonth = new Date(calendarMonth.getFullYear(), calendarMonth.getMonth() + Number(button.dataset.month), 1);
        await loadCalendar();
      } else if (button.dataset.day) {
        const day = button.dataset.day;
        selectedDay = day;
        if (period !== 'custom') await loadSummary();
        $('calendar').querySelectorAll('[data-day]').forEach((b) => { b.classList.toggle('is-selected', b.dataset.day === day); b.setAttribute('aria-pressed', String(b.dataset.day === day)); });
        if (dayMap) { dayMap.remove(); dayMap = null; }
        $('day-content').innerHTML = '<p>Loading day...</p>';
        await loadDay(day);
      }
    } catch (error) { $('day-content').innerHTML = `<p class="error">${esc(errorText(error))}</p>`; }
  };
  renderPeriodBar();
  await Promise.all([loadCalendar(), loadDay(selectedDay), loadSummary()]);
}
