"""Validated user settings stored in the engine metadata."""
import json
import re

DEFS = {
    'clinical_ai_privacy_ack': ('Enable clinical AI after reviewing de-identified data policy', 'bool', False),
    'ai_interview_assist': ('AI interview assist', 'bool', False),
    'ai_report_assist': ('AI report assist', 'bool', False),
    'ai_reply_reading': ('AI reply reading', 'select', 'ask', ['off', 'ask', 'auto']),
    'proda_auto_sms_login': ('Automatic PRODA SMS login', 'bool', False),
    'autopilot_paused': ('Pause messaging autopilot', 'bool', False),
    **{f'auto_{kind}': (f'Automatic {kind.replace(chr(95), chr(32))}', 'select', 'ask', ['off', 'ask', 'auto']) for kind in ('confirmation', 'thanks_decline', 'follow_up', 'reminder')},
    'follow_up_after_hours': ('Follow-up after hours', 'int', 24, 12, 96),
    'reminder_from_hour': ('Reminder from local hour', 'int', 16, 9, 19),
    'home_address': ('Home address / start location', 'text', ''),
    'end_address': ('Default end point', 'text', ''),
    'day_start_time': ('Usual start time', 'time', '08:30'),
    'pharmacist_name': ('Pharmacist name', 'text', ''),
    'pharmacist_phone': ('Pharmacist phone', 'text', ''),
    'pharmacist_credential': ('Pharmacist credential', 'text', 'Credentialed Consultant Pharmacist'),
    'pharmacist_credential_confirmed': ('Pharmacist credential above is confirmed for reports', 'bool', False),
    'referral_valid_days': ('Referral valid days', 'int', 90, 30, 365),
    'referral_warn_days': ('Referral warning days', 'int', 30, 1, 90),
    'followup_first_after_days': ('First follow-up after days', 'int', 30, 1, None),
    'followup_window_end_days': ('Follow-up window end days', 'int', 270, 1, None),
    'new_hmr_after_months': ('New HMR after months', 'int', 24, 1, None),
    'interview_export_format': ('Interview export format', 'select', 'docx', ['docx', 'pdf', 'both']),
    'report_use_original_builder': ('Use original Word report builder (requires locally installed Word and private approved assets; output cannot be signed off)', 'bool', False),
    'flow_includes_ai_assist': ('Include AI assist in auto flow', 'bool', False),
}

def get(conn, key):
    spec = DEFS[key]; row = conn.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
    if not row: return spec[2]
    if spec[1] == 'int': return int(row[0])
    if spec[1] == 'bool': return row[0].lower() == 'true'
    return row[0]

def listing(conn):
    result = []
    for key, spec in DEFS.items():
        item = dict(key=key, label=spec[0], type=spec[1], value=get(conn, key), default=spec[2])
        if spec[1] == 'int':
            item['min'] = spec[3]
            if spec[4] is not None: item['max'] = spec[4]
        if spec[1] == 'select': item['options'] = spec[3]
        result.append(item)
    return result

def update(conn, values):
    if not isinstance(values, dict): raise ValueError('invalid settings')
    for key, value in values.items():
        if key not in DEFS: raise ValueError('unknown setting: ' + str(key))
        spec = DEFS[key]; kind = spec[1]
        valid = (kind == 'text' and isinstance(value, str) and len(value) <= 20000 or
                 kind == 'time' and isinstance(value, str) and re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]', value) is not None or
                 kind == 'bool' and type(value) is bool or
                 kind == 'select' and value in spec[3] or
                 kind == 'int' and type(value) is int and value >= spec[3] and (spec[4] is None or value <= spec[4]))
        if not valid: raise ValueError('invalid setting: ' + key)
    for key, value in values.items():
        conn.execute('INSERT OR REPLACE INTO meta(key,value) VALUES (?,?)', (key, str(value).lower() if type(value) is bool else str(value)))
