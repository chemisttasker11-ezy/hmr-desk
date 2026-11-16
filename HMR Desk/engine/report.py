"""Local report editor data and reusable finding search."""
import datetime as dt
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading

import brainstorm
import db
import interview
import jobs
import manual_defaults

WIDTHS = {'meds': 4, 'otc': 3, 'ceased': 3, 'path': 5}
REVIEW = ['thanks', 'reason', 'intro', 'followup']
_cache = {}
_lock = threading.RLock()

def validate(data):
    if not isinstance(data, dict) or not jobs.REPORT_KEYS <= data.keys(): raise ValueError('report spec missing required keys')
    for key in jobs.REPORT_KEYS - set(WIDTHS) - {'issues'}:
        if not isinstance(data[key], str): raise ValueError('invalid ' + key)
    for key, width in WIDTHS.items():
        if not isinstance(data[key], list) or any(not isinstance(row, list) or len(row) != width or any(not isinstance(x, str) for x in row) for row in data[key]): raise ValueError('invalid ' + key + ' rows')
    if not isinstance(data['issues'], list) or any(not isinstance(i, dict) or any(not isinstance(i.get(k), str) or not i[k].strip() for k in ('title', 'rec', 'rationale')) for i in data['issues']): raise ValueError('invalid issues')
    if 'needs_review' in data and (not isinstance(data['needs_review'], list) or any(x not in REVIEW for x in data['needs_review'])): raise ValueError('invalid needs_review')

def load(conn, patient, ai=False):
    target = jobs.patient_folder(patient) / ('report_spec.ai.json' if ai else 'report_spec.json')
    if not target.is_file(): return {'saved': False}
    data = json.loads(target.read_text(encoding='utf-8'))
    validate(data)
    if not ai: data['interview_newer'] = 'interview_revision' in data and interview.revision(jobs.patient_folder(patient) / 'interview.json') != data['interview_revision']
    if not ai:
        import pathology_records
        data['pathology_newer'] = 'pathology_revision' in data and pathology_records.revision(pathology_records.file_for(patient)) != data['pathology_revision']
    return data

def save(conn, patient, data):
    with _lock: return _save(conn, patient, data)

def _save(conn, patient, data):
    validate(data)
    data = {k: v for k, v in data.items() if k not in ('interview_newer', 'pathology_newer')}
    target = jobs.report_spec_path(patient)
    if target.exists():
        fd, temp = tempfile.mkstemp(dir=target.parent); os.close(fd)
        try: shutil.copyfile(target, temp); os.replace(temp, str(target) + '.bak')
        finally:
            if os.path.exists(temp): os.unlink(temp)
    jobs.atomic_json(target, data)
    db.log(conn, patient['id'], 'report_saved', {}, 'api')
    return data

def placeholders(data):
    return manual_defaults.unresolved(data)

def observations(record):
    d = record.get('details', {}); lines = []
    rows = record.get('obs', [])
    for r in [r for r in rows if r[0] != 'Height / weight / BMI'] + [r for r in rows if r[0] == 'Height / weight / BMI']:
        if r[0] == 'Height / weight / BMI':
            parts = []
            for key in ('height', 'weight', 'bmi'):
                value = d.get(key + '_actual', '')
                referral = d.get(key + '_referral', '')
                if d.get(key + '_as_listed') and referral: value = referral
                elif not value and referral: value = referral + ' (referral)'
                if value: parts.append(key.title() + ': ' + value)
            value = '; '.join(parts) or (r[2] or (r[1] + ' (referral)' if r[1] else ''))
        else: value = r[2] or (r[1] + ' (referral)' if r[1] else '')
        if value: lines.append(r[0] + ': ' + value)
    for key, label in (('home_bp', 'Home BP readings'), ('home_bgl', 'Home blood glucose readings')):
        if d.get(key): lines.append(label + ': ' + d[key])
    for key, label in (('smoking', 'Smoking'), ('alcohol', 'Alcohol')):
        if d.get(key) and d[key] != 'unknown': lines.append(label + ': ' + interview.CHOICE_LABELS[key][d[key]] + (' — ' + d[key + '_details'] if d.get(key + '_details') else ''))
    if record.get('mobility'): lines.append('Mobility: ' + record['mobility'])
    for key, label, choices in (('missed_doses', 'Missed doses', ('sometimes', 'often')), ('device_technique', 'Device technique', ('issues',))):
        if d.get(key) in choices: lines.append(label + ': ' + interview.CHOICE_LABELS[key][d[key]].lower() + (' — ' + d[key + '_details'] if d.get(key + '_details') else ''))
    if d.get('swallowing') == 'yes': lines.append('Swallowing problems reported' + (': ' + d['swallowing_details'] if d.get('swallowing_details') else ''))
    for key, label in interview.SYMPTOMS.items():
        if d.get(key) == 'yes': lines.append('Reports ' + label.lower() + (': ' + d[key + '_details'] if d.get(key + '_details') else ''))
    if d.get('recent_change') == 'yes': lines.append('Recent hospital or specialist change: ' + (d.get('recent_change_details') or 'yes'))
    return '\n'.join(lines)

def intro_text(record, name, visit):
    d = record['details']
    if not any(d.get(k) for k in ('present', 'lives', 'manager', 'daa')): return ''
    text = 'I visited ' + name + (' on ' + visit if visit else '')
    if d.get('present') == 'with_other': text += ', with ' + (d.get('present_details') or 'a carer or family member') + ' present'
    elif d.get('present') == 'alone': text += ' and saw the patient alone'
    sentences = [text + '.']
    if d.get('lives'): sentences.append(name + ' lives ' + {'alone': 'alone', 'partner': 'with a partner', 'family': 'with family', 'other': 'in another living arrangement'}[d['lives']] + '.')
    manager = {'self': 'the patient', 'other': d.get('manager_details') or 'someone else'}.get(d.get('manager'))
    clause = 'Medicines are managed by ' + manager if manager else ''
    if d.get('daa') == 'yes':
        aid = 'a dose administration aid' + (' (' + interview.CHOICE_LABELS['daa_type'][d['daa_type']] + ')' if d.get('daa_type') else '') + (' packed by ' + d['daa_pharmacy'] if d.get('daa_pharmacy') else '')
        clause = clause + ', using ' + aid if clause else 'Medicines are supplied using ' + aid
    elif d.get('daa') == 'no': clause = clause + ', without a dose administration aid' if clause else 'No dose administration aid is used'
    if clause: sentences.append(clause + '.')
    return ' '.join(sentences)

def _derived(conn, patient):
    folder = jobs.patient_folder(patient); target = jobs.report_spec_path(patient)
    import api
    with interview.record_lock(patient):
        has_interview = (folder / 'interview.json').is_file()
        if not (folder / 'confirmed_meds.json').is_file(): raise ValueError('confirm the medicine list first')
        if not api.confirmed_medicines_current(patient): raise ValueError('Medicine use changed; review and confirm medicines first')
        record = interview.load(conn, patient); p = dict(patient); h = record['header']
    if not has_interview:
        confirmed = json.loads((folder / 'confirmed_meds.json').read_text(encoding='utf-8'))
        record['meds'] = [[r[0], '', '', '', 'Brand: ' + r[1] if r[1] else ''] for r in confirmed['meds']]
        record['details']['meds'] = [{'packed': '', 'as_instructed': False} for _ in record['meds']]
        record['allergies'] = '\n'.join(confirmed['allergies'])
    referral_rows = record['meds']
    referral_meta = record['details']['meds']
    other_rows = record['other_meds']
    other_meta = record['details']['other_meds']
    def actual(r, m):
        if m.get('use_status') == 'unknown': return 'Not yet confirmed' + ('; previously recorded directions: ' + r[2] if r[2] else ('; referral: ' + r[1] if r[1] else '')) + ('; used ' + m['prn_use'] if m.get('prn_use') else '')
        return (r[2] or ('Not yet confirmed; referral: ' + r[1] if r[1] else 'Not yet confirmed')) + ('; used ' + m['prn_use'] if m.get('prn_use') else '')
    def other_actual(r, m):
        if m.get('use_status') == 'unknown': return 'Not yet confirmed' + ('; previously recorded directions: ' + r[1] if r[1] else '')
        return r[1] or 'Not yet confirmed'
    def other_note(r, m):
        return ' | '.join(filter(None, [*r[2:], interview.use_text(m)]))
    def referral_note(r, m):
        return '\n'.join(filter(None, (r[4], 'DAA: ' + m['packed'] if m['packed'] else '')))
    import pathology_records
    clinical_pathology = pathology_records.load(patient)
    verified_pathology = clinical_pathology['records']
    verification = clinical_pathology.get('verification', {})
    pathology_table = [[r[0], r[1], '', '',
                        'UNVERIFIED legacy interview entry — confirm against original source | ' +
                        ' '.join(filter(None, (r[3], ('Date: ' + r[2]) if r[2] else '')))]
                       for r in record['pathology'] if any(r)]
    for result in verified_pathology:
        if not result['test'].strip(): continue
        pathology_table.append([
            result['test'],
            result['value'], result['unit'], result['reference_interval'],
            ' | '.join(filter(None, (
                ('Verified by ' + verification[result['id']]['verified_by'] +
                 ' at ' + verification[result['id']]['verified_at']
                 if result['verified'] and result['id'] in verification else
                 'LEGACY VERIFICATION — reviewer not recorded; check original source'
                 if result['verified'] else 'UNVERIFIED — check original source'),
                'Sample: ' + result['sample_date'] if result['sample_date'] else '',
                'Source: ' + result['source'] if result['source'] else '',
                result['comment'],
            )))
        ])
    dates = list(dict.fromkeys(
        [r[2] for r in record['pathology'] if r[2]] +
        [r['sample_date'] for r in verified_pathology if r['sample_date']]
    ))
    return record, dict(conditions=record['conditions'], allergies=record['allergies'], obs=observations(record), meds=[[r[0], actual(r, m), referral_note(r, m), ''] for r, m in zip(referral_rows, referral_meta) if any(r) and m.get('use_status') != 'not_using'] + [[r[0], other_actual(r, m), ' | '.join(filter(None, r[2:])), ''] for r, m in zip(other_rows, other_meta) if any(r) and m.get('use_status') != 'not_using' and m.get('kind') not in ('otc', 'complementary')], otc=[[r[0], other_actual(r, m), ' | '.join(filter(None, r[2:]))] for r, m in zip(other_rows, other_meta) if any(r) and m.get('use_status') != 'not_using' and m.get('kind') in ('otc', 'complementary')], ceased=[[r[0], r[1], ' | '.join(filter(None, ['Referral medicine', r[2], '\n'.join(filter(None, (referral_note(r, m), interview.use_text(m))))]))] for r, m in zip(referral_rows, referral_meta) if any(r) and m.get('use_status') == 'not_using'] + [[r[0], r[1], ' | '.join(filter(None, ['Found during interview', other_note(r, m)]))] for r, m in zip(other_rows, other_meta) if any(r) and m.get('use_status') == 'not_using'], path=pathology_table), ', '.join(dates)

def start(conn, patient):
    folder = jobs.patient_folder(patient); target = jobs.report_spec_path(patient)
    if target.exists(): raise FileExistsError('report spec already exists')
    record, derived, dates = _derived(conn, patient); p = dict(patient); h = record['header']
    name = p['name']; gp = p.get('gp') or h['gp'] or ''
    data = manual_defaults.initial_text(name, gp)
    address = ', '.join(filter(None, (p.get('address'), p.get('suburb'))))
    patient_lines = [name, 'DOB: ' + (p.get('dob') or h['dob']), 'Medicare No: ' + (p.get('medicare') or ''), 'Address: ' + address, 'Phone: ' + (p.get('phone') or '')]
    doctor_lines = [gp, p.get('clinic') or '', 'Request date: ' + (p.get('referral_date') or '')]
    import steps
    visit = steps.event_date(conn, patient, 'visited') or p.get('visit_date') or h['visit'].split(' ')[0]
    data.update(out=str(folder / ('HMR ' + re.sub(r'[<>:"/\\|?*]', '', name).rstrip(' .') + '.docx')), name=name, assess_date=visit, report_date=dt.date.today().strftime('%d/%m/%Y'), patient='\n'.join(patient_lines), doctor='\n'.join(filter(None, doctor_lines)), dear='Dear ' + gp + ',', path_date=dates, issues=[], needs_review=REVIEW.copy())
    data.update(derived, interview_revision=record['revision'], interview_reason=record['details']['reason'], pathology_revision=__import__('pathology_records').revision(__import__('pathology_records').file_for(patient)))
    intro = intro_text(record, name, visit)
    if intro: data['intro'] = intro
    if record['details']['reason'].strip():
        data['reason'] = record['details']['reason']; data['needs_review'].remove('reason')
    validate(data)
    with target.open('x', encoding='utf-8') as f: json.dump(data, f, ensure_ascii=False, indent=2)
    db.log(conn, patient['id'], 'report_started', {}, 'job')
    return data

def refresh(conn, patient):
    with _lock: return _refresh(conn, patient)

def _refresh(conn, patient):
    target = jobs.report_spec_path(patient)
    if not target.is_file(): raise ValueError('report spec does not exist')
    data = json.loads(target.read_text(encoding='utf-8')); validate(data)
    record, derived, _ = _derived(conn, patient)
    import pathology_records
    data.update(derived, interview_revision=record['revision'], interview_reason=record['details']['reason'],
                pathology_revision=pathology_records.revision(pathology_records.file_for(patient)))
    save(conn, patient, data)
    db.log(conn, patient['id'], 'report_refreshed', {}, 'job')
    return data

def _read(path):
    stamp = path.stat().st_mtime_ns
    if path not in _cache or _cache[path][0] != stamp: _cache[path] = (stamp, path.read_text(encoding='utf-8'))
    return _cache[path][1]

def library(q):
    words = q.casefold().split()
    if not words: return []
    refs = jobs.SKILL / 'references'; result = []
    text = _read(refs / 'finding-library.md') if (refs / 'finding-library.md').is_file() else ''
    for section in re.split(r'(?m)(?=^## )', text):
        if not section.startswith('## '): continue
        title, _, body = section.partition('\n')
        if all(w in section.casefold() for w in words): result.append(dict(source='library', title=title[3:].strip(), rec=body.strip(), rationale='', context='Full library section; split and edit for this patient.'))
    for line in (_read(refs / 'case-index.jsonl') if (refs / 'case-index.jsonl').is_file() else '').splitlines():
        if not line.strip(): continue
        case = json.loads(line)
        for finding in case.get('findings', []):
            # Reject any unredacted name or birth date rather than exposing it.
            fields = [str(finding.get(k, '')) for k in ('title', 'rec', 'rationale')]
            if re.search(r'(?i)\b(?:mr|mrs|ms|miss|dr)\.?\s+(?!\[pt\])[A-Z][a-z]+|\b(?:dob|date of birth|born)\b', ' '.join(fields)): continue
            context = str(case.get('Current Conditions', ''))
            if re.search(r'(?i)\b(?:mr|mrs|ms|miss|dr)\.?\s+(?!\[pt\])[A-Z][a-z]+|\b(?:dob|date of birth|born)\b', context): continue
            searchable = ' '.join(fields + [context] + [' '.join(m.get('row', [])) for m in case.get('meds', [])] + case.get('pathology', [])).casefold()
            if all(w in searchable for w in words): result.append(dict(source='past case', title=fields[0], rec=fields[1], rationale=fields[2], context=context))
    result = result[:30]
    brain_count = 0
    for section in brainstorm.sections(refs / 'brainstorm-v2.pdf'):
        if all(w in (section['title'] + ' ' + section['text']).casefold() for w in words):
            snippet = brainstorm.snippet(section['text'], [re.escape(w) for w in words])
            result.append(dict(source=f"Brainstorm V2 p.{section['page']}", title=section['title'], snippet=snippet, rec=snippet, rationale='', context=''))
            brain_count += 1
            if brain_count == 10: break
    return result
