'use strict';
// Fail-closed default for the stdio MCP. Every registered tool must be classified here; an unclassified tool is refused.
// Classes: read (code-read: no write, no outbound), ui (local window control, label guard is best effort), save (a local
// record save; engine route code-read for outbound calls, none found, not yet runtime-proven), blocked (settings, run/job,
// messages, portal/auth, patient state changes, anything not proven local). Lifted only by HMR_MCP_ALLOW_RESTRICTED=1.
const READ = ['hmr_status', 'hmr_today', 'hmr_patients', 'hmr_patient', 'hmr_tasks', 'hmr_interview_get', 'hmr_report_get', 'hmr_suggestions',
  'hmr_library', 'hmr_agents', 'hmr_settings_get', 'hmr_attention', 'hmr_timeline', 'hmr_messages', 'hmr_medicines_get', 'hmr_consent_preview',
  'hmr_followup_get', 'hmr_job_get', 'hmr_days', 'hmr_summary', 'hmr_appointments', 'hmr_day', 'hmr_day_plan', 'hmr_intake'];
const UI = ['app_state', 'app_identity', 'app_ui_snapshot', 'app_ui_click', 'app_ui_fill', 'app_navigate', 'app_screenshot', 'app_patient_focus'];
const SAVE = ['hmr_interview_save', 'hmr_report_save', 'hmr_medicines_save', 'hmr_followup_save', 'hmr_patient_action'];
// hmr_patient_action: only these local-record actions; every state change (booking, decline, visit, sign-off, claim...) is blocked.
const SAVE_PATIENT_ACTIONS = ['note', 'update', 'interactions_manual'];
const BLOCKED = ['hmr_run', 'hmr_task_cancel', 'hmr_settings_set', 'hmr_agent_select', 'hmr_message_approve', 'hmr_messages_check', 'hmr_message_draft',
  'hmr_message_discard', 'hmr_message_resolve', 'hmr_followup_export', 'hmr_task_result', 'hmr_job_start', 'hmr_appointment_save',
  'hmr_appointment_delete', 'hmr_day_plan_save', 'hmr_day_route', 'hmr_intake_correction', 'hmr_referral_review', 'hmr_referral_commit',
  'hmr_report_refresh', 'hmr_report_demographics', 'app_tab', 'app_page_buttons', 'app_page_click', 'app_page_text', 'app_results',
  'app_auth_status', 'app_proda_login'];
const CLASS = {};
for (const [list, c] of [[READ, 'read'], [UI, 'ui'], [SAVE, 'save'], [BLOCKED, 'blocked']]) for (const n of list) { if (CLASS[n]) throw new Error('duplicate classification ' + n); CLASS[n] = c; }
function refusal(name, args) {
  const c = CLASS[name];
  if (!c) return 'unclassified tool';
  if (c === 'blocked') return 'blocked tool';
  if (name === 'hmr_patient_action' && !SAVE_PATIENT_ACTIONS.includes(args && args.action)) return 'patient state change';
  return null;
}
module.exports = { CLASS, SAVE_PATIENT_ACTIONS, refusal };
