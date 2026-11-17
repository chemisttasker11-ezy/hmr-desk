const http = require('node:http');
const path = require('node:path');
const os = require('node:os');
const today = new Date();
const day = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(
  2,
  '0',
)}`;
const patient = {
  id: 1,
  name: 'Alex Example',
  suburb: 'Sampleton',
  gp: 'Dr Example',
  phone: '0400000000',
  state: 'confirmed',
  status_text: 'Scheduled',
  visit_date: day,
  visit_time: '10:30',
  visit_end: '11:30',
  folder: 'Alex Example',
  has_pathology: 0,
  has_sheet: 0,
  address: '1 Example Street',
  note: 'Call on arrival',
  dob: '01-Jan-1980',
  sex: 'F',
  medicare: '1234567890',
  irn: '1',
  ihi: '',
};
const listPatient = (({
  id,
  name,
  suburb,
  gp,
  phone,
  state,
  status_text,
  visit_date,
  visit_time,
  folder,
  has_pathology,
  has_sheet,
}) => ({
  id,
  name,
  suburb,
  gp,
  phone,
  state,
  status_text,
  visit_date,
  visit_time,
  folder,
  has_pathology,
  has_sheet,
  next_step: 'collect pathology',
}))(patient);
const secondPatient = {
  ...listPatient,
  id: 2,
  name: 'Sam Example',
  state: 'visited',
  status_text: 'Visited',
  next_step: 'confirm medicines',
  folder: 'Sam Example',
};
const pastPatient = { ...listPatient, id: 3, name: 'Casey Test', state: 'offered', status_text: 'Offered', visit_date: '2020-01-01', visit_time: '09:00', offered_date: '2019-12-01' };
Object.assign(listPatient, { stage: 'ready', stage_step: 'interview_pack', next_step: 'make interview sheet', flags: [] });
Object.assign(secondPatient, { state: 'signed_off', stage: 'report', stage_step: 'report_draft', flags: [] });
Object.assign(pastPatient, { stage: 'booking', stage_step: 'offer', next_step: 'offer a time', flags: ['offer_passed'] });
const sentPatient = { ...listPatient, id: 4, name: 'Morgan Example', state: 'sent', stage: 'claim', stage_step: 'claim', flags: [] };
const followupPatient = { ...listPatient, id: 5, name: 'Taylor Example', state: 'claimed', stage: 'followup', stage_step: 'followup1', flags: [] };
Object.assign(patient, { stage: 'ready', stage_step: 'interview_pack', next_step: 'make interview sheet', flags: [] });
const extraStages = ['intake', 'done', 'hold', 'declined', 'expired', 'archived'].map((stage, index) => ({ ...listPatient, id: index + 6, name: `Example ${stage}`, stage, stage_step: '', flags: stage === 'archived' ? ['archived'] : [] }));
const mockPatients = [listPatient, secondPatient, pastPatient, sentPatient, followupPatient, ...extraStages];
const messageDrafts = { 8: { id: 8, patient_id: 3, answers_message_id: 9, state: 'draft', body: 'Please call us.' } };
let mockReply = { id: 9, patient_id: 3, name: pastPatient.name, direction: 'incoming', body: 'I am not sure, please call me.', ai_summary: 'Requests a call', ai_intent: 'unclear', ai_draft_id: 8, offered_at: '2020-01-01T09:00' };
let messageId = 100;
const exampleNextSteps = ['confirm medicines', 'check interactions', 'build report', 'prepare interview sheet'];
secondPatient.next_step = exampleNextSteps[0];
let agents = {
  default: 'Example agent',
  per_step: {},
  agents: [
    {
      name: 'Example agent',
      type: 'cli',
      enabled: true,
      route: 'prompt',
      command: ['example'],
      env: {},
      stdin: true,
      has_key: false,
    },
  ],
};
const settings = [
  { key: 'home_address', label: 'Home address / start location', type: 'text', value: '1 Example St, Runaway Bay', default: '' },
  { key: 'end_address', label: 'Default end point', type: 'text', value: '', default: '' },
  { key: 'day_start_time', label: 'Day start time', type: 'time', value: '08:30', default: '08:30' },
  { key: 'practice_name', label: 'Practice name', type: 'text', value: 'Example practice', default: '' },
  { key: 'review_days', label: 'Review days', type: 'int', value: 30, default: 30, min: 1, max: 365 },
  { key: 'reminders', label: 'Reminders', type: 'bool', value: true, default: true },
  {
    key: 'report_format',
    label: 'Report format',
    type: 'choice',
    value: 'docx',
    default: 'docx',
    options: ['docx', 'pdf'],
  },
];
const queue = [
  {
    id: 1,
    folder: patient.folder,
    folder_path: process.env.HMR_MOCK_PATIENT_DIR || path.join(os.tmpdir(), 'hmr-example'),
    last: 'Example',
    dob: patient.dob,
    sex: patient.sex,
    medicare: patient.medicare,
    irn: patient.irn,
    ihi: '',
  },
];
const interviews = {};
const blankInterview = (p) => ({
  header: {
    name: p.name,
    dob: p.dob || '',
    age: '',
    address: p.address || '',
    phone: p.phone,
    gp: p.gp,
    visit: p.visit_date,
    referral_date: '',
    pharmacist: '',
  },
  details: { version: 1, reason: 'Review medicines', sx_falls: 'yes', sx_falls_details: 'One fall', swallowing: 'no', present: 'with_other', present_details: 'Family member', meds: (process.env.HMR_SHOTS ? [1, 2, 3] : [1]).map((_, i) => ({ packed: '', as_instructed: false, prn_use: i === 0 ? 'Once a week' : '' })), other_meds: process.env.HMR_SHOTS ? [{ kind: 'otc' }] : [] },
  notes: '',
  concerns: '',
  social: '',
  mobility: '',
  exercise: '',
  alcohol_smoking: '',
  manages_meds: '',
  allergies: '',
  obs: [['Blood pressure', '', '']],
  conditions: '',
  meds: process.env.HMR_SHOTS ? [['Example medicine A', 'Once daily', 'When required', '', ''], ['Example medicine B', 'Twice daily', '', '', ''], ['Example medicine C', 'Once daily', '', '', '']] : [['Example medicine', 'Once daily', 'When required', '', '']],
  other_meds: process.env.HMR_SHOTS ? [['Example vitamin', 'Once daily', '', '']] : [],
  pathology: [],
  clarify: [],
  consent: { signed: false, date: '', by: 'patient', relationship: 0, authorised_name: '' },
  sources: ['meds from referral - check'],
  saved: false,
  ...(process.env.HMR_SHOTS ? { revision: 'mock-0', consent_file: '' } : {}),
});
interviews[2] = { ...blankInterview(secondPatient), saved: true, allergies: 'Example allergy', meds: [['Example medicine', 'Once daily', 'Once daily', '', 'Interview note']], details: { meds: [{ use_status: 'taking', packed: 'packed' }], other_meds: [] } };
const reports = {};
const reportBackups = {};
const drafts = {};
const blankReport = (p) => ({
  out: 'Example.docx',
  name: p.name,
  assess_date: '',
  report_date: '',
  patient: p.name,
  doctor: p.gp,
  dear: 'Dear Doctor,',
  thanks: 'Thank you for the referral.',
  reason: '',
  intro: '',
  conditions: '',
  allergies: '',
  obs: '',
  meds: [],
  otc: [],
  ceased: [],
  issues: [],
  path_date: '',
  path: [],
  followup: '',
  needs_review: ['intro'],
  interview_newer: p.id === 2,
});
const sampleFindings = [
  { title: 'Example finding', rec: 'Review the example.', rationale: 'An example observation.' },
  { title: 'Another finding', rec: 'Consider follow-up.', rationale: 'A second example observation.' },
];
if (process.env.HMR_SHOTS) reports[2] = { ...blankReport(secondPatient), issues: sampleFindings };
const library = [
  {
    source: 'library',
    title: 'Example finding',
    rec: 'Review the example.',
    rationale: 'An example observation.',
    context: 'Synthetic example',
  },
  {
    source: 'past case',
    title: 'Example follow-up',
    rec: 'Consider follow-up.',
    rationale: 'An example only.',
    context: '',
  },
];
const medicines = {};
const medicineInterviewSnapshots = {};
const visits = { 1: [], 2: [{ visit_date: day, kind: 'hmr', report_sent: null, claimed: null }], 3: [] };
const proposal = (id) => {
  const interview = interviews[id];
  if (!interview?.saved) return { meds: [], allergies: [], proposed: true };
  const usage = interview.details?.meds || [];
  const meds = (interview.meds || []).filter((row, i) => usage[i]?.use_status === 'taking').map(row => [row[0], '']);
  const found = (interview.other_meds || []).filter((row, i) => interview.details?.other_meds?.[i]?.use_status === 'taking').map(row => [row[0], '']);
  return { meds: [...meds, ...found].filter(row => row[0]), allergies: String(interview.allergies || '').split(/\r?\n/).filter(Boolean), proposed: true };
};
const stepsCatalog = [
  { name: 'pathology', label: 'Collect pathology', runs_in: 'mhr', ai_off: false },
  { name: 'interview_sheet', label: 'Make interview sheet', runs_in: 'engine', ai_off: false },
  { name: 'interview_assist', label: 'Interview assist (AI)', runs_in: 'ai', ai_off: false },
  { name: 'report_extract', label: 'Extract report', runs_in: 'engine', ai_off: false },
  { name: 'interactions', label: 'Check interactions', runs_in: 'emims', ai_off: false },
  { name: 'report_start', label: 'Start report', runs_in: 'engine', ai_off: false },
  { name: 'report_assist', label: 'Draft with AI', runs_in: 'ai', ai_off: false },
  { name: 'report_build', label: 'Build report', runs_in: 'engine', ai_off: false },
  { name: 'claim', label: 'Claim', runs_in: 'ppa', ai_off: false },
  { name: 'register_xlsx', label: 'Export register', runs_in: 'engine', ai_off: false },
  { name: 'intake_dry', label: 'Review intake', runs_in: 'engine', ai_off: false },
  { name: 'intake_apply', label: 'Apply intake', runs_in: 'engine', ai_off: false },
];
function patientSteps(p) {
  const visited = ['visited', 'report_drafted', 'signed_off', 'sent', 'claimed'].includes(p.state);
  return [
    ['pathology', 'mhr', !visited, visited ? 'patient is not scheduled' : '', false],
    ['interview_sheet', 'engine', !visited, visited ? 'patient is not scheduled' : '', false],
    ['interview_assist', 'ai', !visited, visited ? 'patient is not scheduled' : '', false],
    ['report_extract', 'engine', false, visited ? 'already done' : 'visit not recorded', visited],
    [
      'interactions',
      'emims',
      visited && !!medicines[p.id],
      visited ? (medicines[p.id] ? '' : 'confirm the medicine list first') : 'visit not recorded',
      false,
    ],
    [
      'report_start',
      'engine',
      visited && !!medicines[p.id],
      visited ? 'confirm medicines first' : 'visit not recorded',
      !!reports[p.id],
    ],
    [
      'report_build',
      'engine',
      !!reports[p.id],
      visited ? 'report spec missing' : 'patient is not awaiting report',
      ['report_drafted', 'signed_off', 'sent', 'claimed'].includes(p.state),
    ],
    ['claim', 'ppa', false, 'report not marked sent', p.state === 'claimed'],
  ].map(([name, runs_in, ready, reason, done]) => ({ name, runs_in, ready, reason, done }));
}
const jobs = {};
const tasks = [];
let rows = [
  {
    file: 'example.pdf',
    kind: 'referral',
    fields: { name: 'Alex Example', suburb: 'Sampleton' },
    flags: ['Check details'],
    planned: 'Alex Example',
    applied: '',
  },
];
let appointments = [{ id: 1, date: day, start: '12:15', end: '13:00', title: 'Pharmacy team meeting', place: 'Runaway Bay Pharmacy', note: '' }];
let appointmentId = 2;
const plans = {};
function dayPlan(date) {
  const overrides = plans[date] || {};
  const value = (key) => settings.find((item) => item.key === key).value;
  const defaults = { start_time: value('day_start_time'), start_place: value('home_address'), end_place: value('end_address') || value('home_address') };
  return { date, ...Object.fromEntries(Object.entries(defaults).map(([key, fallback]) => [key, overrides[key] || fallback])), defaults: Object.fromEntries(Object.keys(defaults).map((key) => [key, !overrides[key]])) };
}
function respond(req, res, body) {
  const url = new URL(req.url, 'http://localhost');
  let data;
  if (url.pathname === '/api/status') {
    data = {
      patients: { confirmed: 1 },
      messages: {},
      gateway_online: false,
      outbox_mode: 'test',
      sending_window: 'on',
    };
  } else if (url.pathname === '/api/summary') {
    const from = url.searchParams.get('from'), to = url.searchParams.get('to');
    const rows = from <= day && day <= to ? [{ date: day, total: 6, confirmed: 4, waiting: 2, declined: 0, hold: 1, not_sent: 0 }] : [];
    data = { days: rows, totals: rows[0] || { total: 0, confirmed: 0, waiting: 0, declined: 0, hold: 0, not_sent: 0 } };
  } else if (url.pathname === '/api/appointments' && req.method === 'GET') {
    data = appointments.filter((a) => a.date >= url.searchParams.get('from') && a.date <= url.searchParams.get('to'));
  } else if (url.pathname === '/api/appointments' && req.method === 'POST') {
    const a = { ...body, id: body.id ?? appointmentId++ };
    appointments = [...appointments.filter((item) => item.id !== a.id), a]; data = a;
  } else if (/^\/api\/appointments\/[^/]+\/delete$/.test(url.pathname) && req.method === 'POST') {
    appointments = appointments.filter((a) => String(a.id) !== url.pathname.split('/')[3]); data = { ok: true };
  } else if (url.pathname === '/api/days') {
    data = url.searchParams.get('from') <= day && day <= url.searchParams.get('to') ? [{ date: day, total: 6, confirmed: 4, changed: 1 }] : [];
  } else if (/^\/api\/days\/\d{4}-\d{2}-\d{2}\/plan$/.test(url.pathname)) {
    const date = url.pathname.split('/')[3];
    if (req.method === 'POST') plans[date] = { ...plans[date], ...body };
    data = dayPlan(date);
  } else if (/^\/api\/days\/\d{4}-\d{2}-\d{2}\/route$/.test(url.pathname)) {
    const plan = dayPlan(url.pathname.split('/')[3]);
    data = { urls: [], stops: [], skipped: [], start: { place: plan.start_place, time: plan.start_time }, end: { place: plan.end_place, time: '' } };
  } else if (/^\/api\/days\/\d{4}-\d{2}-\d{2}$/.test(url.pathname)) {
    const date = url.pathname.split('/')[3];
    const visits = date === day ? [
      { names: [patient.name], time: '09:00', status: 'confirmed', status_text: 'Confirmed', suburb: patient.suburb, address: patient.address, phone: '0400 000 001' },
      { names: ['Sam Example'], time: '09:45', status: 'confirmed', status_text: 'Confirmed by SMS reply', suburb: 'Runaway Bay', address: '2 Example St, Runaway Bay', phone: '0400 000 002', note: 'Ring bell twice', ll: [-27.913, 153.399] },
      { names: ['Casey Test'], time: '11:00', status: 'offered', status_text: 'Offered', suburb: 'Southport', ll: [-27.967, 153.4] },
      { names: ['Drew Demo'], time: '13:30', status: 'confirmed', status_text: 'Confirmed', suburb: 'Hollywell', address: '4 Demo Ave, Hollywell', ll: [-27.9, 153.395] },
      { names: ['Eli Mock'], time: '14:15', status: 'changed', status_text: 'Asked to change', suburb: 'Labrador', ll: [-27.944, 153.4] },
      { names: ['Frankie Trial'], time: '15:00', status: 'confirmed', status_text: 'Confirmed', suburb: 'Coombabah', ll: [-27.91, 153.37] },
    ] : [];
    data = { plan: dayPlan(date), summary: { total: visits.length, confirmed: 4, first: visits.length ? '09:00' : '', last: visits.length ? '15:40' : '', suburbs: visits.length ? ['Hollywell', 'Runaway Bay', 'Southport'] : [] }, home: { name: 'Home', ll: [-27.93, 153.38] }, stops: [
      ...visits,
      ...appointments.filter((a) => a.date === date).map((a) => ({ ...a, time: a.start, status: 'meeting', address: a.place })),
    ] };
  } else if (url.pathname === '/api/attention') {
    const examples = [
      ['today_visits', 'Today visits', 'open_interview', { time: '09:00', suburb: 'Pimpama', pathology_done: false }],
      ['visits_to_check', 'Visits to check', 'visited', { detail: 'Visit needs recording' }],
      ['replies_waiting', 'Replies waiting', 'open_messages', { reply: 'Please call me' }],
      ['offers_passed', 'Offers passed', 'offer', { visit_date: day, visit_time: '09:00' }],
      ['prep', 'Preparation', 'pathology', { suburb: 'Pimpama', pathology_done: false }],
      ['reports', 'Reports', 'open_report', { detail: 'Report waiting' }],
      ['claims', 'Claims', 'claim', { detail: 'Claim due' }],
      ['followups', 'Follow-ups', 'followup1', { detail: 'Follow-up due' }],
      ['referrals', 'Referrals', 'expired', { days_left: -22 }],
      ['stuck', 'Stuck', 'retry', null],
    ];
    data = { generated_at: new Date().toISOString(), groups: examples.map(([key, title, action, extra]) => ({ key, title, items: extra ? [{ patient_id: patient.id, name: patient.name, action, ...extra }] : [] })) };
  } else if (url.pathname === '/api/today') {
    data = {
      visits: [patient],
      alerts: [
        { id: 1, name: patient.name, type: 'missing pathology' },
        ...['follow-up 1 due', 'follow-up 2 due', 'new HMR possible'].map((type) => ({
          id: 2,
          name: secondPatient.name,
          type,
          date: day,
          window_end: type.startsWith('follow-up') ? day : null,
        })),
      ],
    };
  } else if (process.env.HMR_SHOTS && url.pathname === '/api/referrals/commit' && req.method === 'POST') {
    res.statusCode = 400; data = { error: 'Synthetic review error: check the referral details.' };
  } else if (process.env.HMR_SHOTS && url.pathname === '/api/shots/referrals') {
    data = { rows: [
      { file: 'synthetic-referral.pdf', status: 'review', kind: 'referral', token: 'synthetic-review', fields: { name: 'Alex Example', dob: '1980-01-01', gp: 'Dr Example', referral_date: '2026-10-20' }, flags: ['Check referral details before adding.'] },
      { file: 'synthetic-duplicate.pdf', status: 'duplicate', duplicate_kind: 'identity', kind: 'referral', token: 'synthetic-duplicate', fields: { name: 'Sam Example', dob: '1975-02-03', gp: 'Dr Example' } },
      { file: 'synthetic-unreadable.pdf', status: 'error', message: 'Synthetic PDF could not be read.' },
      { file: 'synthetic-not-referral.pdf', status: 'rejected', message: 'No referral identified.' },
    ] };
  } else if (url.pathname === '/api/patients') {
    const q = (url.searchParams.get('q') || '').toLowerCase();
    data = {
      patients: mockPatients.filter(
        (p) =>
          (url.searchParams.get('archived') === '1' || p.stage !== 'archived') &&
          (!q || [p.name, p.suburb, p.gp, p.phone].some((x) => x.toLowerCase().includes(q))) &&
          (!url.searchParams.get('state') || p.state === url.searchParams.get('state')),
      ),
    };
  } else if (/^\/api\/patients\/\d+\/interview$/.test(url.pathname)) {
    const id = Number(url.pathname.split('/')[3]);
    const p = id === 1 ? patient : mockPatients.find((item) => item.id === id);
    if (!p) {
      res.statusCode = 404;
      data = { error: 'patient not found' };
    } else if (req.method === 'POST') {
      const current = interviews[id] || blankInterview(p);
      if (process.env.HMR_SHOTS && body.revision !== current.revision) { res.statusCode = 409; data = { error: 'interview conflict' }; }
      else data = interviews[id] = { ...body, saved: true, ...(process.env.HMR_SHOTS ? { revision: `mock-${Number(current.revision.split('-')[1]) + 1}` } : {}) };
    }
    else data = interviews[id] || blankInterview(p);
  } else if (/^\/api\/patients\/\d+\/suggestions$/.test(url.pathname) && req.method === 'GET') {
    data = {
      suggestions: [
        {
          title: 'Example review',
          rec: 'Review the example.',
          rationale: 'An example observation.',
          source: 'library',
          why: ['An example item is present.'],
          missing: ['Confirm the example'],
        },
        {
          title: 'Example follow-up',
          rec: 'Consider follow-up.',
          rationale: 'A synthetic reason.',
          source: 'brainstorm',
          why: ['A follow-up was noted.'],
          missing: [],
        },
      ],
      context_gaps: ['Example context is incomplete.'],
    };
  } else if (url.pathname === '/api/library') {
    const q = (url.searchParams.get('q') || '').toLowerCase();
    data = {
      results: q ? library.filter((item) => Object.values(item).some((value) => value.toLowerCase().includes(q))) : [],
    };
  } else if (/^\/api\/patients\/\d+\/report\/refresh$/.test(url.pathname) && req.method === 'POST') {
    const id = Number(url.pathname.split('/')[3]), report = reports[id], interview = interviews[id];
    if (!report) { res.statusCode = 404; data = { error: 'report spec missing' }; }
    else if (!medicines[id]) { res.statusCode = 400; data = { error: 'confirm medicines first' }; }
    else if (medicineInterviewSnapshots[id] !== JSON.stringify(interview || null)) { res.statusCode = 400; data = { error: 'medicine list is out of date' }; }
    else {
      reportBackups[id] = structuredClone(report);
      const source = interview || blankInterview(mockPatients.find(p => p.id === id));
      data = reports[id] = { ...report, conditions: source.conditions || '', allergies: source.allergies || '',
        obs: (source.obs || []).map(row => row.filter(Boolean).join(': ')).join('\n'),
        meds: medicines[id].meds.map(row => { const i = (source.meds || []).findIndex(m => m[0] === row[0]); const med = source.meds?.[i]; const found = (source.other_meds || []).find(m => m[0] === row[0]); const packed = source.details?.meds?.[i]?.packed; return [row[0], med ? (med[2] || med[1] || '') : (found?.[1] || ''), [med?.[4] || found?.[3], packed ? `DAA: ${packed}` : ''].filter(Boolean).join('\n'), '']; }),
        otc: (source.other_meds || []).filter((row, i) => source.details?.other_meds?.[i]?.use_status === 'taking').map(row => [row[0], row[1], row[3]]),
        ceased: (source.meds || []).filter((row, i) => source.details?.meds?.[i]?.use_status === 'not_using').map(row => [row[0], row[1], source.details.meds[(source.meds || []).indexOf(row)].use_reason || '']),
        path: (source.pathology || []).map(row => Array.from({ length: 5 }, (_, i) => row[i] || '')),
        ...(report.needs_review?.includes('reason') ? { reason: source.concerns || '' } : {}), interview_newer: false };
    }
  } else if (/^\/api\/patients\/\d+\/report$/.test(url.pathname)) {
    const id = Number(url.pathname.split('/')[3]);
    if (!mockPatients.some((p) => p.id === id)) {
      res.statusCode = 404;
      data = { error: 'patient not found' };
    } else if (req.method === 'POST') {
      const text = [
        'out',
        'name',
        'assess_date',
        'report_date',
        'patient',
        'doctor',
        'dear',
        'thanks',
        'reason',
        'intro',
        'conditions',
        'allergies',
        'obs',
        'path_date',
        'followup',
      ];
      const valid =
        text.every((key) => typeof body[key] === 'string') &&
        [
          ['meds', 4],
          ['otc', 3],
          ['ceased', 3],
          ['path', 5],
        ].every(
          ([key, width]) =>
            Array.isArray(body[key]) &&
            body[key].every(
              (row) => Array.isArray(row) && row.length === width && row.every((v) => typeof v === 'string'),
            ),
        ) &&
        Array.isArray(body.issues) &&
        body.issues.every((issue) => ['title', 'rec', 'rationale'].every((key) => typeof issue[key] === 'string')) &&
        (body.needs_review === undefined ||
          (Array.isArray(body.needs_review) && body.needs_review.every((v) => typeof v === 'string')));
      if (!valid) {
        res.statusCode = 400;
        data = { error: 'invalid report spec' };
      } else data = reports[id] = body;
    } else data = (url.searchParams.has('ai') ? drafts[id] : reports[id]) || { saved: false };
  } else if (/^\/api\/patients\/\d+\/meds$/.test(url.pathname)) {
    const id = Number(url.pathname.split('/')[3]);
    if (!mockPatients.some((p) => p.id === id)) {
      res.statusCode = 404;
      data = { error: 'patient not found' };
    } else if (req.method === 'GET') data = medicines[id] || proposal(id);
    else if (req.method === 'POST') {
      if (!body || Array.isArray(body) || Object.keys(body).sort().join(',') !== 'allergies,meds') {
        res.statusCode = 400;
        data = { error: 'invalid medicine list' };
      } else if (
        !Array.isArray(body.meds) ||
        body.meds.length > 60 ||
        body.meds.some(
          (row) => !Array.isArray(row) || row.length !== 2 || row.some((x) => typeof x !== 'string') || !row[0].trim(),
        )
      ) {
        res.statusCode = 400;
        data = { error: 'invalid medicines' };
      } else if (
        !Array.isArray(body.allergies) ||
        body.allergies.length > 60 ||
        body.allergies.some((x) => typeof x !== 'string')
      ) {
        res.statusCode = 400;
        data = { error: 'invalid allergies' };
      } else {
        medicineInterviewSnapshots[id] = JSON.stringify(interviews[id] || null);
        data = medicines[id] = { meds: body.meds, allergies: body.allergies, confirmed_at: new Date().toISOString() };
      }
    }
  } else if (/^\/api\/patients\/\d+\/messages$/.test(url.pathname) && req.method === 'POST') {
    const p = mockPatients.find((item) => item.id === Number(url.pathname.split('/')[3]));
    if (!p) { res.statusCode = 404; data = { error: 'patient not found' }; }
    else if (!['offer', 'change_request', 'change'].includes(body.kind) || !body.date || !body.time) { res.statusCode = 400; data = { error: 'invalid message' }; }
    else {
      const id = messageId++;
      data = messageDrafts[id] = { id, patient_id: p.id, ...body, state: 'draft', body: `Hello ${p.name}, can we visit on ${body.date} at ${body.time}?` };
    }
  } else if (/^\/api\/messages\/\d+\/resolve$/.test(url.pathname) && req.method === 'POST') {
    mockReply = null; data = { ok: true };
  } else if (/^\/api\/messages\/\d+\/(approve|discard)$/.test(url.pathname) && req.method === 'POST') {
    const [, , , id, operation] = url.pathname.split('/');
    const draft = messageDrafts[id];
    if (!draft) { res.statusCode = 404; data = { error: 'message not found' }; }
    else {
      if (operation === 'approve') {
        const p = mockPatients.find((item) => item.id === draft.patient_id);
        if (draft.kind && draft.kind !== 'change_request') Object.assign(p, { state: 'offered', status_text: 'Offered', visit_date: draft.date, visit_time: draft.time, offered_date: day });
        if (p?.id === 1) Object.assign(patient, p);
      }
      delete messageDrafts[id]; data = { ...draft, state: operation === 'approve' ? 'offered' : 'discarded' };
    }
  } else if (/^\/api\/patients\/\d+$/.test(url.pathname) && req.method === 'GET') {
    const id = Number(url.pathname.split('/')[3]);
    const p = id === 1 ? patient : mockPatients.find((item) => item.id === id);
    if (!p) { res.statusCode = 404; res.setHeader('Content-Type', 'application/json'); return res.end(JSON.stringify({ error: 'patient not found' })); }
    data = {
      ...p,
      can_undo: true, undo_label: 'previous stage', folder_check: { actual: 'Scheduled', expected: 'Visited', ok: false },
      suggested_kind: p.visit_date && p.visit_time ? 'change' : 'offer',
      change_kinds: p.visit_date && p.visit_time ? ['change_request', 'change'] : [],
      events: [],
      messages: process.env.HMR_SHOTS && p.id === 1 ? [
        { id: 201, patient_id: 1, direction: 'out', state: 'sent', body: 'Synthetic appointment offer.', created_at: '2026-10-23T09:00:00' },
        { id: 202, patient_id: 1, direction: 'in', state: 'received', body: 'Synthetic reply: that time works.', created_at: '2026-10-23T10:00:00' },
      ] : [],
      files: { folder: process.env.HMR_SHOTS && p.id === 1 ? ['Synthetic referral.pdf', 'Synthetic interview.docx'] : p.id === 2 ? ['MIMS interactions.txt'] : [], pathology: process.env.HMR_SHOTS && p.id === 1 ? ['Synthetic pathology.pdf'] : [] },
      followups: null,
      visits: visits[p.id],
      steps: patientSteps(p),
      tasks: tasks.filter((t) => t.patient_id === id).slice(-30).reverse(),
    };
  } else if (url.pathname === '/api/messages/board') {
    data = { outbox_mode: 'test', test_patient_id: 3, needs_you: mockReply ? [mockReply, messageDrafts[8]].filter(Boolean) : [], waiting: [], upcoming: [], recent: [] };
  } else if (/^\/api\/patients\/\d+\/timeline$/.test(url.pathname)) {
    data = { milestones: { referral_date: '2026-10-20', first_contact: '2026-10-22', confirmed: '2026-10-24', followup1_due: '2026-11-01' }, entries: [{ at: '2026-10-24T09:00', at_text: '24/10/2026', label: 'Confirmed', detail: 'Visit booked by phone' }] };
  } else if (/^\/api\/patients\/\d+\/action$/.test(url.pathname) || url.pathname === '/api/pathology/result') {
    if (body.action === 'followup_done')
      (visits[Number(url.pathname.split('/')[3])] ||= []).unshift({
        kind: body.kind,
        visit_date: body.date,
        report_sent: null,
        claimed: null,
      });
    const target = mockPatients.find(p => p.id === Number(url.pathname.split('/')[3]));
    if (target && body.action === 'archive') target.stage = 'archived';
    if (target && body.action === 'unarchive') target.stage = 'done';
    if (target && body.action === 'resume') target.stage = 'booking';
    if (body.action === 'signed_off') secondPatient.state = 'signed_off';
    data = { ok: true };
  } else if (url.pathname === '/api/settings' && req.method === 'GET') {
    data = { settings };
  } else if (url.pathname === '/api/settings' && req.method === 'POST') {
    const bad = Object.entries(body).find(([key, value]) => {
      const item = settings.find((entry) => entry.key === key);
      return (
        !item ||
        (item.type === 'int'
          ? !Number.isInteger(value) || value < item.min || value > item.max
          : item.type === 'bool'
            ? typeof value !== 'boolean'
            : typeof value !== 'string' || (item.type === 'choice' && !item.options.includes(value)))
      );
    });
    if (bad) {
      res.statusCode = 400;
      data = { error: `Invalid ${bad[0]}` };
    } else {
      for (const item of settings) if (Object.hasOwn(body, item.key)) item.value = body[item.key];
      data = { ok: true };
    }
  } else if (url.pathname === '/api/agents' && req.method === 'GET') {
    data = agents;
  } else if (url.pathname === '/api/agents' && req.method === 'POST') {
    const { key, ...agent } = body;
    agents.agents = [...agents.agents.filter((a) => a.name !== agent.name), { ...agent, has_key: !!key }];
    data = { ok: true };
  } else if (url.pathname === '/api/agents/delete' && req.method === 'POST') {
    agents.agents = agents.agents.filter((a) => a.name !== body.name);
    if (agents.default === body.name) agents.default = null;
    for (const step of Object.keys(agents.per_step)) {
      if (agents.per_step[step] === body.name) delete agents.per_step[step];
    }
    data = { ok: true };
  } else if (url.pathname === '/api/agents/select' && req.method === 'POST') {
    if (body.default) agents.default = body.default;
    for (const [step, name] of Object.entries(body.per_step || {})) {
      if (name) agents.per_step[step] = name;
      else delete agents.per_step[step];
    }
    data = { ok: true };
  } else if (url.pathname === '/api/agents/test' && req.method === 'POST') {
    data = { ok: true, reply: 'OK' };
  } else if (url.pathname === '/api/pathology/queue') {
    data = { patients: queue };
  } else if (url.pathname === '/api/mims/lists') {
    data = { lists: [{ ...queue[0], meds: ['paracetamol'], allergies: [] }] };
  } else if (url.pathname === '/api/claims') {
    data = {
      claims: [
        {
          ...queue[0],
          given: 'Alex',
          family: 'Example',
          dob: '1980-01-01',
          medicare: '12345678901',
          interview: day,
          reasons: [],
          outcomes: [],
        },
      ],
    };
  } else if (url.pathname === '/api/run' && req.method === 'GET') {
    const pidParam = url.searchParams.get('patient_id');
    if (pidParam !== null) {
      const pid = Number(pidParam);
      if (!Number.isInteger(pid) || pid <= 0) {
        res.statusCode = 400;
        data = { error: 'invalid patient_id' };
      } else {
        const filtered = tasks.filter((t) => t.patient_id === pid);
        data = { tasks: filtered.slice(-200).reverse(), steps: stepsCatalog };
      }
    } else {
      data = { tasks: [...tasks].reverse(), steps: stepsCatalog };
    }
  } else if (url.pathname === '/api/run' && req.method === 'POST') {
    const ids = body.patient_ids === 'ready' ? [patient.id] : (Array.isArray(body.patient_ids) ? body.patient_ids : []);
    const steps = body.steps === 'auto' ? ['pathology'] : (Array.isArray(body.steps) ? body.steps : []);
    const unknown = steps.filter((s) => !stepsCatalog.some((c) => c.name === s));
    if (unknown.length) {
      res.statusCode = 400;
      data = { error: `invalid steps: ${unknown.join(', ')}` };
    } else {
      const queued = [];
      const skipped = [];
      for (const step of steps)
        for (const pid of ids) {
          if (tasks.some((t) => t.patient_id === pid && t.step === step && ['queued', 'waiting'].includes(t.state))) {
            skipped.push({ patient_id: pid, step, reason: 'task already queued, running or waiting' });
            continue;
          }
          const waiting = { pathology: 'mhr', interactions: 'emims', claim: 'ppa' }[step];
          const name = mockPatients.find((p) => p.id === pid)?.name || 'Patient';
          const task = {
            id: (tasks.length + 1).toString(16),
            patient_id: pid,
            patient_name: name,
            name,
            step,
            state: waiting ? 'waiting' : 'done',
            waiting_for: waiting || null,
            output: '',
            created: new Date().toISOString(),
            started: new Date().toISOString(),
            finished: null,
          };
          if (step === 'report_start') reports[pid] ||= blankReport(mockPatients.find((p) => p.id === pid));
          tasks.push(task);
          queued.push(task.id);
        }
      data = { queued, skipped };
    }
  } else if (/^\/api\/run\/[0-9a-f]+\/(cancel|result)$/.test(url.pathname) && req.method === 'POST') {
    const parts = url.pathname.split('/');
    const task = tasks.find((t) => t.id === parts[3]);
    if (task) {
      task.state = parts[4] === 'cancel' ? 'cancelled' : body.state;
      task.output = body.output || '';
      task.finished = new Date().toISOString();
      data = { ok: true };
    }
  } else if (url.pathname === '/api/jobs' && req.method === 'POST') {
    const id = String(Object.keys(jobs).length + 1);
    if (body.job === 'report_start')
      reports[body.patient_id] ||= blankReport(mockPatients.find((p) => p.id === body.patient_id));
    if (body.job === 'report_assist')
      drafts[body.patient_id] = {
        ...blankReport(mockPatients.find((p) => p.id === body.patient_id)),
        issues: sampleFindings,
      };
    if (body.job === 'interview_assist') {
      const record = interviews[body.patient_id] || blankInterview(mockPatients.find((p) => p.id === body.patient_id));
      if (record.meds[0] && !record.meds[0][3]) record.meds[0][3] = 'Check adherence';
      if (!record.clarify.length) record.clarify = ['Confirm medicine use'];
      interviews[body.patient_id] = record;
    }
    const placeholders = body.job === 'report_build' ? (reports[body.patient_id]?.needs_review || []).filter(key => ['thanks', 'reason', 'intro', 'followup'].includes(key) && reports[body.patient_id][key] === blankReport(mockPatients.find(p => p.id === body.patient_id))[key]) : [];
    jobs[id] = {
      state: placeholders.length ? 'failed' : 'done',
      output:
        placeholders.length ? `Review placeholder fields: ${placeholders.join(', ')}` : body.job === 'interview_pack'
          ? 'Interview exported. Consent template not found.'
          : body.job === 'interview_assist'
            ? 'Suggestions ready.'
            : body.job === 'register_xlsx'
              ? 'saved C:\\Example\\Booking_Register.xlsx'
              : body.job === 'import_history'
                ? 'Found 1 past patient.'
                : body.job === 'import_history_apply'
                  ? 'History import applied.'
                  : '',
    };
    data = { id };
  } else if (/^\/api\/jobs\/\d+$/.test(url.pathname)) {
    data = jobs[url.pathname.split('/').pop()];
  } else if (url.pathname === '/api/intake') {
    data = { rows };
  } else if (url.pathname === '/api/intake/correction' && req.method === 'POST') {
    rows = rows.map((row) => (row.file === body.file ? { ...row, fields: { ...row.fields, ...body.fields } } : row));
    data = { ok: true };
  }
  if (!data) {
    res.statusCode = 404;
    data = { error: 'not found' };
  }
  res.setHeader('Content-Type', 'application/json');
  res.end(JSON.stringify(data));
}
const server = http.createServer((req, res) => {
  let body = '';
  req.on('data', (chunk) => {
    body += chunk;
  });
  req.on('end', () => respond(req, res, body ? JSON.parse(body) : {}));
});
server.listen(Number(process.env.PORT || 8765), '127.0.0.1', () => {
  console.log(`Mock API listening ${server.address().port}`);
});
