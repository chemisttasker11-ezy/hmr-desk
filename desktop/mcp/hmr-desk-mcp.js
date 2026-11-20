const fs = require('node:fs/promises');
const path = require('node:path');
const readline = require('node:readline');
const string = { type: 'string', minLength: 1 };
const id = { type: 'integer', minimum: 1 };
const obj = { type: 'object' };
const WHITELISTED_AUTH_STATUSES = new Set([
  'disabled',
  'pending',
  'waiting_sms',
  'submitted',
  'completed',
  'needs_user_action',
  'unavailable',
]);
const WHITELISTED_AUTH_REASONS = new Set([
  'not_started',
  'manual_fallback',
  'expired',
  'ambiguous',
  'invalid_code',
  'credentials_missing',
  'mhr_inactive',
  'proda_auto_sms_login_disabled',
  'harness_disabled',
  'navigation_cancelled',
  'service_selection_needed',
  'challenge_mismatch',
  'tab_not_open',
  'unavailable',
]);
function filterAuthStatus(raw) {
  if (!raw || typeof raw !== 'object') return { status: 'unavailable', reason: 'unavailable' };
  const status = WHITELISTED_AUTH_STATUSES.has(raw.status) ? raw.status : 'unavailable';
  const out = { status };
  if (raw.reason && WHITELISTED_AUTH_REASONS.has(raw.reason)) {
    out.reason = raw.reason;
  }
  return out;
}

const defs = [
  ['hmr_status', 'Get engine status; never sends SMS.', {}, [], 'GET', '/api/status'],
  ['hmr_today', 'Get today’s visits and alerts.', {}, [], 'GET', '/api/today'],
  ['hmr_patients', 'Search patients by state or text.', { state: string, q: string }, [], 'GET', '/api/patients'],
  ['hmr_patient', 'Get patient details.', { id }, ['id'], 'GET', '/api/patients/:id'],
  [
    'hmr_patient_action',
    'Record a patient action; never sends a report or submits a claim.',
    { id, action: string, fields: obj },
    ['id', 'action', 'fields'],
    'POST',
    '/api/patients/:id/action',
  ],
  [
    'hmr_run',
    'Queue engine steps; PPA fills only and never submits a claim.',
    {
      steps: {
        anyOf: [
          { type: 'array', items: string },
          { type: 'string', enum: ['auto'] },
        ],
      },
      patient_ids: {
        anyOf: [
          { type: 'array', items: id },
          { type: 'string', enum: ['ready'] },
        ],
      },
    },
    ['steps', 'patient_ids'],
    'POST',
    '/api/run',
  ],
  ['hmr_tasks', 'List recent engine tasks.', {}, [], 'GET', '/api/run'],
  ['hmr_task_cancel', 'Cancel a queued or waiting task.', { id: string }, ['id'], 'POST', '/api/run/:id/cancel'],
  ['hmr_interview_get', 'Read an interview record.', { id }, ['id'], 'GET', '/api/patients/:id/interview'],
  [
    'hmr_interview_save',
    'Save an interview record.',
    { id, record: obj },
    ['id', 'record'],
    'POST',
    '/api/patients/:id/interview',
  ],
  [
    'hmr_report_get',
    'Read a report or separate AI draft.',
    { id, ai: { type: 'boolean' } },
    ['id'],
    'GET',
    '/api/patients/:id/report',
  ],
  [
    'hmr_report_save',
    'Save a report spec; does not send it.',
    { id, spec: obj },
    ['id', 'spec'],
    'POST',
    '/api/patients/:id/report',
  ],
  [
    'hmr_suggestions',
    'Get suggestions that require pharmacist review.',
    { id },
    ['id'],
    'GET',
    '/api/patients/:id/suggestions',
  ],
  ['hmr_library', 'Search the report text library.', { q: string }, ['q'], 'GET', '/api/library'],
  ['hmr_settings_get', 'Read engine settings.', {}, [], 'GET', '/api/settings'],
  [
    'hmr_settings_set',
    'Update settings; outbox mode and agent keys are excluded.',
    { values: obj },
    ['values'],
    'POST',
    '/api/settings',
  ],
  ['hmr_agents', 'List agents without keys.', {}, [], 'GET', '/api/agents'],
  ['app_state', 'Get the current screen, tabs and queued one-off count.', {}, [], 'POST', '/state'],
  ['app_identity', 'Which running copy this control endpoint belongs to: app process id, data folder, profile. Check before any other app_* call.', {}, [], 'POST', '/identity'],
  ['app_ui_snapshot', 'Structured list of the visible controls in the app window (ref, label, value, options, disabled, blocked) plus page text. Refs come from the latest snapshot.', { max: { type: 'integer', minimum: 1, maximum: 200000 } }, [], 'POST', '/ui/snapshot'],
  ['app_ui_click', 'Click a control by ref from app_ui_snapshot. Controls that send, sign off, claim or sign in are refused.', { ref: { type: 'string', pattern: '^s[0-9]{1,6}[.][0-9]{1,6}$' } }, ['ref'], 'POST', '/ui/click'],
  ['app_ui_fill', 'Set a text field, select (option value or text) or checkbox by ref. Give value, or checked for checkboxes. Password, code and key fields are refused.', { ref: { type: 'string', pattern: '^s[0-9]{1,6}[.][0-9]{1,6}$' }, value: { type: 'string' }, checked: { type: 'boolean' } }, ['ref'], 'POST', '/ui/fill'],
  ['app_navigate', 'Navigate to a rail screen or browser tab.', { page: { type: 'string', enum: ['today', 'book', 'visit', 'report', 'claim', 'followup', 'activity', 'calendar', 'My calendar', 'my calendar', 'my-calendar', 'messages', 'run', 'patients', 'interview', 'intake', 'reports', 'mhr', 'emims', 'ppa', 'amh', 'sheet', 'settings'] } }, ['page'], 'POST', '/navigate'],
  [
    'app_tab',
    'Control a tab; PPA fills only and load is restricted to its host.',
    { site: string, action: { type: 'string', enum: ['open', 'back', 'reload', 'toggle', 'load'] }, url: string },
    ['site', 'action'],
    'POST',
    '/tab',
  ],
  [
    'app_page_buttons',
    'List visible helper buttons and links; sign-in pages are refused.',
    { site: string },
    ['site'],
    'POST',
    '/page/buttons',
  ],
  [
    'app_page_click',
    'Click a visible helper element by id; sign-in pages are refused.',
    { site: string, id: string },
    ['site', 'id'],
    'POST',
    '/page/click',
  ],
  [
    'app_page_text',
    'Read visible tab text; sign-in pages are refused.',
    { site: string, max: { type: 'integer', minimum: 1, maximum: 200000 } },
    ['site'],
    'POST',
    '/page/text',
  ],
  [
    'app_screenshot',
    'Capture the window or tab; sign-in pages are refused.',
    { site: string },
    [],
    'POST',
    '/page/screenshot',
  ],
  ['app_results', 'Get this session’s helper results and saved filenames.', {}, [], 'POST', '/results'],
  ['app_auth_status', 'Get authentication status for PRODA/MHR; returns only whitelisted status.', {}, [], 'POST', '/auth/status'],
  ['app_proda_login', 'Trigger PRODA login flow for My Health Record.', {}, [], 'POST', '/auth/proda/login'],
];
// The supported operations are deliberately enumerated; no generic endpoint tool is exposed.
const date = { type: 'string', pattern: '^\\d{4}-\\d{2}-\\d{2}$' };
const choice = (...values) => ({ type: 'string', enum: values });
const number = { type: 'integer', enum: [1, 2] };
const followFields = { date: {type:'string'}, method: choice('phone','in person'), spoke_with: {type:'string'}, med_changes: {type:'string'}, recommendations: {type:'array',items:{type:'array',items:{type:'string'},minItems:3,maxItems:3},maxItems:80}, issues: {type:'string'}, outcome: {type:'string'}, notes: {type:'string'} };
const record = (properties, required = Object.keys(properties)) => ({type:'object', properties, required, additionalProperties:false});
const demographicKey = choice('name','assess_date','patient','doctor','dear');
const usageItem = record({name:{type:'string'}, status:choice('taking','not_using','unknown'), detail:{type:'string'}, source:choice('Referral medicine','Found during interview'), directions:{type:'array',items:{type:'string'},minItems:2,maxItems:2}});
const referralFields = record(Object.fromEntries(['name','phone','address','suburb','gp','clinic','referral_date','dob','sex','medicare','irn','ihi'].map(key => [key,{type:'string'}])), ['name']);
const kinds = choice('offer','change','change_request','follow_up','confirmation','thanks_decline','reminder');
defs.push(
  ['hmr_attention','Get active attention groups.',{},[],'GET','/api/attention'],
  ['hmr_timeline','Get patient timeline.',{id},['id'],'GET','/api/patients/:id/timeline'],
  ['hmr_messages','Get the active patient message board.',{},[],'GET','/api/messages/board'],
  ['hmr_message_approve','Approve a patient draft in test mode only; requires explicit user authorization and confirm_send=true.',{id:string,confirm_send:{type:'boolean',enum:[true]},confirm_expired:{type:'boolean',enum:[true]}},['id','confirm_send'],'POST','/api/messages/:id/approve'],
  ['hmr_messages_check','Process queued test messages and check patient replies in test mode only; requires explicit user authorization and confirm_send=true.',{confirm_send:{type:'boolean',enum:[true]}},['confirm_send'],'POST','/api/messages/check'],
  ['hmr_message_draft','Create a template message draft.',{id,kind:kinds,date,time:{type:'string'}},['id','kind'],'POST','/api/patients/:id/messages'],
  ['hmr_message_discard','Discard a message draft.',{id:string},['id'],'POST','/api/messages/:id/discard'],
  ['hmr_message_resolve','Resolve an inbound reply.',{id:string,as:choice('yes','decline','new_time','call','done')},['id','as'],'POST','/api/messages/:id/resolve'],
  ['hmr_medicines_get','Get medicines.',{id},['id'],'GET','/api/patients/:id/meds'],
  ['hmr_medicines_save','Save confirmed medicines with reviewed interview use and explicit taking alternatives for stopped overlaps.',{id,meds:{type:'array',items:{type:'array',items:{type:'string'},minItems:2,maxItems:2},maxItems:60},allergies:{type:'array',items:{type:'string'},maxItems:60},medicine_snapshot_sha256:{type:'string',pattern:'^[0-9a-f]{64}$'},interview_usage:{type:'array',items:usageItem},alternatives:{type:'array',items:{anyOf:[usageItem,{type:'null'}]},maxItems:60}},['id','meds','allergies'],'POST','/api/patients/:id/meds'],
  ['hmr_consent_preview','Read the consent preview image and metadata including its revision.',{id},['id'],'GET','/api/patients/:id/consent/preview'],
  ['hmr_followup_get','Get a follow-up form.',{id,number},['id','number'],'GET','/api/patients/:id/followup/:number'],
  ['hmr_followup_save','Save a follow-up form.',{id,number,form:record(followFields)},['id','number','form'],'POST','/api/patients/:id/followup/:number'],
  ['hmr_followup_export','Export a follow-up form.',{id,number},['id','number'],'POST','/api/patients/:id/followup/:number/export'],
  ['hmr_task_result','Complete or fail a waiting task; provide the verified MIMS result filename for interaction completion.',{id:string,state:choice('done','failed'),output:{type:'string'},mims_result:string},['id','state'],'POST','/api/run/:id/result'],
  ['hmr_job_start','Start a known engine job; PPA never submits claims.',{job:choice('interview_pack','interview_sheet','report_start','report_build','report_assist','report_draft','interview_assist','report_extract'),patient_id:id,format:choice('docx','pdf','both')},['job','patient_id'],'POST','/api/jobs'],
  ['hmr_job_get','Get a job status.',{id:string},['id'],'GET','/api/jobs/:id'],
  ['hmr_days','List calendar days.',{from:date,to:date},['from','to'],'GET','/api/days'],
  ['hmr_summary','Get period summary.',{from:date,to:date},['from','to'],'GET','/api/summary'],
  ['hmr_appointments','List appointments.',{from:date,to:date},['from','to'],'GET','/api/appointments'],
  ['hmr_appointment_save','Create or update an appointment.',{id,date,start:string,end:string,title:string,place:{type:'string'},note:{type:'string'}},['date','start','end','title'],'POST','/api/appointments'],
  ['hmr_appointment_delete','Delete an appointment.',{id},['id'],'POST','/api/appointments/:id/delete'],
  ['hmr_day','Get a calendar day.',{date},['date'],'GET','/api/days/:date'],
  ['hmr_day_plan','Get a day plan.',{date},['date'],'GET','/api/days/:date/plan'],
  ['hmr_day_plan_save','Save a day plan.',{date,plan:record({start_time:{type:'string'},start_place:{type:'string'},end_place:{type:'string'}},[])},['date','plan'],'POST','/api/days/:date/plan'],
  ['hmr_day_route','Get a day route.',{date,include:choice('confirmed','all')},['date'],'GET','/api/days/:date/route'],
  ['hmr_intake','Read legacy intake report rows; these may be stale and are not the current referral review.',{},[],'GET','/api/intake'],
  ['hmr_intake_correction','Correct legacy intake report fields only; does not update the current referral review or create a patient.',{file:string,fields:record({name:{type:'string'},dob:{type:'string'},sex:{type:'string'},medicare:{type:'string'},irn:{type:'string'},ihi:{type:'string'},address:{type:'string'},suburb:{type:'string'},phone:{type:'string'},gp:{type:'string'},referral_date:{type:'string'},clinic:{type:'string'}},[])},['file','fields'],'POST','/api/intake/correction'],
  ['hmr_referral_review','Review explicitly selected local referral PDFs; returns extracted fields, flags and duplicate or error feedback without creating patients.',{paths:{type:'array',items:string,minItems:1,maxItems:100}},['paths'],'POST','/api/referrals/review'],
  ['hmr_referral_commit','After deliberate review, add one referral patient using its review token and corrected fields.',{token:{type:'string',pattern:'^[0-9a-f]{32}$'},fields:referralFields,confirm:{type:'boolean',enum:[true]}},['token','fields','confirm'],'POST','/api/referrals/commit'],
  ['hmr_agent_select','Select configured agents by default and/or step.',{default:string,per_step:record({interview_assist:{anyOf:[string,{type:'null'}]},report_draft:{anyOf:[string,{type:'null'}]},report_assist:{anyOf:[string,{type:'null'}]}},[])},[],'POST','/api/agents/select'],
  ['hmr_report_refresh','Refresh the report from current patient records; demographic blocks the pharmacist edited are kept and reported unless named in replace_demographics. Does not sign off or send.',{id,replace_demographics:{type:'array',items:demographicKey,maxItems:5}},['id'],'POST','/api/patients/:id/report/refresh'],
  ['hmr_report_demographics','Resolve listed report demographic mismatches: replace writes the patient record value, keep records an acknowledgement bound to the text and record value. Does not sign off or send.',{id,action:choice('replace','keep'),keys:{type:'array',items:demographicKey,minItems:1,maxItems:5}},['id','action','keys'],'POST','/api/patients/:id/report/demographics'],
  ['app_patient_focus','Open a patient workspace, interview, report or follow-up.',{id,view:choice('patient','interview','report','followup'),number,tab:choice('Overview','Conversation','Activity','Files'),layout:choice('split','list','patient')},['id','view'],'POST','/patient/focus'],
);
// Extend existing read tools without changing their established arguments.
defs.find(d => d[0] === 'hmr_tasks')[2].patient_id = id;
defs.find(d => d[0] === 'hmr_patients')[2].archived = {type:'boolean'};
const tools = defs.map(([name, description, properties, required]) => ({
  name,
  description,
  inputSchema: { type: 'object', properties, required, additionalProperties: false },
}));
function valid(value, schema) {
  if (schema.anyOf) return schema.anyOf.some((s) => valid(value, s));
  if (schema.type === 'null') return value === null;
  if (schema.enum && !schema.enum.includes(value)) return false;
  if (schema.type === 'object') return !!value && typeof value === 'object' && !Array.isArray(value) && (!schema.properties || (Object.entries(value).every(([k,v]) => schema.properties[k] && valid(v,schema.properties[k])) && (schema.required || []).every(k => Object.hasOwn(value,k))));
  if (schema.type === 'array') return Array.isArray(value) && value.length >= (schema.minItems ?? 0) && value.length <= (schema.maxItems ?? Infinity) && value.every((v) => valid(v, schema.items));
  if (schema.type === 'integer')
    return (
      Number.isSafeInteger(value) && value >= (schema.minimum ?? -Infinity) && value <= (schema.maximum ?? Infinity)
    );
  if (schema.type === 'string') return typeof value === 'string' && value.length >= (schema.minLength ?? 0) && (!schema.pattern || new RegExp(schema.pattern).test(value));
  return typeof value === schema.type;
}
let endpointFileUsed = false;
// Engine address: HMR_API wins; else the live endpoint the packaged app records beside its token; else the
// development default. A recorded endpoint whose engine process is gone fails loudly instead of guessing.
async function resolveBase(app, root, read) {
  endpointFileUsed = false;
  const env = process.env[app ? 'HMR_CONTROL' : 'HMR_API'];
  if (env) return { base: env.replace(/\/$/, '') };
  {
    let rec = null;
    try { rec = JSON.parse(await read(path.join(root, app ? 'control_endpoint.json' : 'engine_endpoint.json'), 'utf8')); } catch {}
    if (rec && typeof rec === 'object') {
      if (typeof rec.url !== 'string' || !/^http:\/\/127\.0\.0\.1:\d{2,5}$/.test(rec.url)) throw Error((app ? 'control_endpoint.json' : 'engine_endpoint.json') + ' is invalid; relaunch the app or set HMR_API');
      if (Number.isInteger(rec.pid)) {
        try { process.kill(rec.pid, 0); } catch (error) { if (error.code === 'ESRCH') throw Error((app ? 'control_endpoint.json' : 'engine_endpoint.json') + ' is stale: its process is not running; relaunch the app or set ' + (app ? 'HMR_CONTROL' : 'HMR_API')); }
      }
      endpointFileUsed = true;
      return { base: rec.url };
    }
  }
  return { base: `http://127.0.0.1:${app ? 8768 : 8767}` };
}
async function call(name, args, fetcher = fetch, read = fs.readFile) {
  const index = defs.findIndex((d) => d[0] === name);
  if (index < 0) throw Error('Unknown tool');
  const schema = tools[index].inputSchema;
  if (
    !valid(args, schema) ||
    schema.required.some((k) => !Object.hasOwn(args, k)) ||
    Object.entries(args).some(([k, v]) => !schema.properties[k] || !valid(v, schema.properties[k]))
  )
    throw Error('Invalid arguments');
  if (
    name === 'hmr_patient_action' &&
    (![
      'book_phone',
      'move',
      'decline_phone',
      'move_declined',
      'expired',
      'claim_now',
      'hold',
      'note',
      'visited',
      'report_drafted',
      'signed_off',
      'followup_done',
      'call',
      'followup_claimed',
      'update', 'archive', 'unarchive', 'resume', 'undo_stage', 'not_visited', 'pathology_outcome', 'interactions_manual', 'report_sent', 'claimed',
    ].includes(args.action) ||
      Object.hasOwn(args.fields, 'action') || Object.hasOwn(args.fields, 'id'))
  )
    throw Error('Invalid action');
  if (name === 'hmr_patient_action') {
    const fields = {
      book_phone:['date','time','end'], move:['date','time','end'], decline_phone:['reason'], move_declined:[], expired:['note'],
      claim_now:['visit_date','report_sent'], hold:['note'], note:['text'], visited:['date'], report_drafted:[], signed_off:[],
      report_sent:['date'], claimed:['date'], followup_done:['kind','date'], followup_claimed:['kind','date'], call:['outcome','note'],
      update:['fields'], archive:[], unarchive:[], resume:[], undo_stage:[], not_visited:[],
      pathology_outcome:['outcome','note'], interactions_manual:['text'],
    };
    if (Object.keys(args.fields).some(k => !fields[args.action].includes(k))) throw Error('Invalid action');
    if (args.action === 'update' && (!args.fields.fields || typeof args.fields.fields !== 'object' || Array.isArray(args.fields.fields) || Object.entries(args.fields.fields).some(([k,v]) => !['phone','address','suburb','postcode','medicare','irn','ihi','dob','sex'].includes(k) || (v !== null && typeof v !== 'string')))) throw Error('Invalid action');
    if (Object.entries(args.fields).some(([k,v]) => k !== 'fields' && typeof v !== 'string')) throw Error('Invalid action');
    if (['followup_done','followup_claimed'].includes(args.action) && !['followup1','followup2'].includes(args.fields.kind)) throw Error('Invalid action');
    if (args.action === 'pathology_outcome' && !['none','access_code','saved_by_hand'].includes(args.fields.outcome)) throw Error('Invalid action');
    if (args.action === 'call' && !['no_answer','left_message','spoke','booked','declined','other'].includes(args.fields.outcome)) throw Error('Invalid action');
  }
  if (['hmr_report_refresh','hmr_report_demographics'].includes(name) && (args.replace_demographics ?? args.keys) && new Set(args.replace_demographics ?? args.keys).size !== (args.replace_demographics ?? args.keys).length) throw Error('Invalid arguments');
  if (name === 'hmr_agent_select' && (!Object.keys(args).length || (args.per_step && !Object.keys(args.per_step).length && !args.default))) throw Error('Invalid arguments');
  if (name === 'app_ui_fill' && ((args.value === undefined) === (args.checked === undefined))) throw Error('Invalid arguments');
  if (name === 'app_patient_focus' && (((args.view === 'followup') !== (args.number !== undefined)) || (args.view !== 'patient' && (args.tab !== undefined || args.layout !== undefined)))) throw Error('Invalid arguments');
  if (
    name === 'hmr_settings_set' &&
    Object.keys(args.values).some((k) => /outbox|mode|key|token|secret|password/i.test(k))
  )
    throw Error('Restricted setting');
  // Sending and clinical authorisation are refused when the server runs as the stdio MCP (HMR_MCP_RESTRICT=1, set by the
  // entry point unless HMR_MCP_ALLOW_RESTRICTED=1). TEST outbox mode is not a safety control: it can still send to the
  // test number. Allow only for a run the user has explicitly approved.
  const RESTRICTED_TOOLS = ['hmr_message_approve', 'hmr_messages_check'];
  const RESTRICTED_ACTIONS = ['signed_off', 'report_sent', 'claimed', 'claim_now'];
  if (process.env.HMR_MCP_RESTRICT === '1' && (RESTRICTED_TOOLS.includes(name) || (name === 'hmr_patient_action' && RESTRICTED_ACTIONS.includes(args.action))))
    throw Error('Restricted: sending and clinical authorisation are disabled for this session');
  if (process.env.HMR_MCP_RESTRICT === '1') {
    const why = require('./tool-policy').refusal(name, args);
    if (why) throw Error('Restricted: ' + why + ' is not allowed by the default policy for this session');
  }
  const [, , , , method, template] = defs[index];
  const app = name.startsWith('app_');
  let route = template.replace(':id', encodeURIComponent(args.id)).replace(':number', encodeURIComponent(args.number)).replace(':date', encodeURIComponent(args.date));
  let body = app ? args : {};
  if (name === 'hmr_patient_action') body = { ...args.fields, action: args.action };
  if (name === 'hmr_run') body = args;
  if (name === 'hmr_message_draft') { const {id, ...fields} = args; body = fields; }
  if (name === 'hmr_message_resolve') body = {as: args.as};
  if (name === 'hmr_message_approve') body = args.confirm_expired ? {confirm_expired:true} : {};
  if (name === 'hmr_messages_check') body = {};
  if (name === 'hmr_medicines_save') { const {id, ...fields} = args; body = fields; }
  if (name === 'hmr_referral_review') body = {paths: args.paths};
  if (name === 'hmr_referral_commit') body = {token: args.token, fields: args.fields};
  if (name === 'hmr_followup_save') body = args.form;
  if (name === 'hmr_day_plan_save') body = args.plan;
  if (name === 'hmr_task_result') { const {id, ...fields} = args; body = fields; }
  if (['hmr_job_start','hmr_appointment_save','hmr_intake_correction','hmr_agent_select'].includes(name)) body = args;
  if (name === 'hmr_interview_save') body = args.record;
  if (name === 'hmr_report_save') body = args.spec;
  if (name === 'hmr_report_refresh') body = args.replace_demographics ? {replace_demographics: args.replace_demographics} : {};
  if (name === 'hmr_report_demographics') body = {action: args.action, keys: args.keys};
  if (name === 'hmr_settings_set') body = args.values;
  if (['hmr_patients','hmr_library','hmr_tasks','hmr_days','hmr_summary','hmr_appointments','hmr_day_route'].includes(name)) {
    const params = {...args}; if (name === 'hmr_patients' && params.archived !== undefined) params.archived = params.archived ? '1' : '0'; if (name === 'hmr_day_route') delete params.date;
    const q = new URLSearchParams(params);
    if (q.size) route += '?' + q;
  }
  if (name === 'hmr_report_get' && args.ai) route += '?ai=1';
  const root = path.join(process.env.USERPROFILE || require('node:os').homedir(), 'HMR-Desk-data');
  let response;
  const target = await resolveBase(app, root, read);
  try {
    const token = (await read(path.join(root, app ? 'app_control_token' : 'api_token'), 'utf8')).trim();
    const base = target.base;
    if (endpointFileUsed) {
      // A live process id is not proof: the id may be reused, or the record may belong to another profile.
      const probe = app
        ? await fetcher(base + '/identity', {method:'POST', headers:{'X-HMR-Control':token, 'Content-Type':'application/json'}, body:'{}'})
        : await fetcher(base + '/api/health', {method:'GET', headers:{'X-HMR-Token':token}});
      if (!probe.ok) throw Error('endpoint probe rejected');
    }
    if (name === 'hmr_message_approve' || name === 'hmr_messages_check') {
      const status = await fetcher(base + '/api/status', {method:'GET', headers:{'X-HMR-Token':token, 'Content-Type':'application/json'}});
      const state = await status.json();
      if (!status.ok || state.outbox_mode !== 'test') throw Error('Messaging actions require test outbox mode');
    }
    response = await fetcher(
      base + route,
      {
        method,
        headers: { [app ? 'X-HMR-Control' : 'X-HMR-Token']: token, 'Content-Type': 'application/json' },
        ...(method === 'POST' ? { body: JSON.stringify(body) } : {}),
      },
    );
  } catch (error) {
    if (error.message === 'Messaging actions require test outbox mode') throw error;
    if (endpointFileUsed) throw Error((app ? 'app control is not responding at the endpoint recorded in control_endpoint.json' : 'engine is not responding at the endpoint recorded in engine_endpoint.json') + ' (stale file, reused process id, another profile, or app closed); relaunch the app or set HMR_API');
    throw Error(app ? 'HMR Desk app is not open' : 'engine is not running');
  }
  const data = await response.json();
  if (!response.ok) throw Error(data.error || `Backend error ${response.status}`);
  if (name === 'hmr_consent_preview') {
    const {png, ...metadata} = data;
    if (typeof png !== 'string' || !png) throw Error('Invalid consent preview');
    return [{type:'image',data:png,mimeType:'image/png'}, {type:'text',text:JSON.stringify(metadata)}];
  }
  if (name === 'app_screenshot') {
    const { png, ...meta } = data;
    if (data.ok === false || typeof png !== 'string' || !png) throw Error('Screenshot refused (' + (data.reason || 'no image') + '); window ' + JSON.stringify(data.window || {}) + '. Refocus the screen and capture again. This check detects only some stale frames; it does not prove a capture is current.');
    return [{ type: 'image', data: png, mimeType: 'image/png' }, { type: 'text', text: JSON.stringify(meta) }];
  }
  if (['app_auth_status', 'app_proda_login'].includes(name)) {
    return [{ type: 'text', text: JSON.stringify(filterAuthStatus(data)) }];
  }
  return [{ type: 'text', text: JSON.stringify(data) }];
}
async function handle(message, fetcher, read) {
  if (!message || message.jsonrpc !== '2.0' || typeof message.method !== 'string')
    return { jsonrpc: '2.0', id: message?.id ?? null, error: { code: -32600, message: 'Invalid Request' } };
  if (!Object.hasOwn(message, 'id')) return null;
  const reply = { jsonrpc: '2.0', id: message.id };
  if (message.method === 'initialize')
    reply.result = {
      protocolVersion: '2024-11-05',
      capabilities: { tools: {} },
      serverInfo: { name: 'hmr-desk', version: '1.0.0' },
    };
  else if (message.method === 'ping') reply.result = {};
  else if (message.method === 'tools/list') reply.result = { tools };
  else if (message.method === 'tools/call') {
    try {
      reply.result = { content: await call(message.params?.name, message.params?.arguments ?? {}, fetcher, read) };
    } catch (error) {
      if (['app_auth_status', 'app_proda_login'].includes(message.params?.name)) {
        reply.result = { content: [{ type: 'text', text: JSON.stringify({ status: 'unavailable', reason: 'unavailable' }) }] };
      } else {
        reply.result = { content: [{ type: 'text', text: error.message }], isError: true };
      }
    }
  } else reply.error = { code: -32601, message: 'Method not found' };
  return reply;
}
if (require.main === module) {
  if (process.env.HMR_MCP_ALLOW_RESTRICTED !== '1') process.env.HMR_MCP_RESTRICT = '1';
  readline.createInterface({ input: process.stdin }).on('line', async (line) => {
    let reply;
    try {
      reply = await handle(JSON.parse(line));
    } catch {
      reply = { jsonrpc: '2.0', id: null, error: { code: -32700, message: 'Parse error' } };
    }
    if (reply) process.stdout.write(JSON.stringify(reply) + '\n');
  });
}
module.exports = { handle, call, tools, filterAuthStatus, WHITELISTED_AUTH_STATUSES, WHITELISTED_AUTH_REASONS };
