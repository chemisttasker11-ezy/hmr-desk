"""Read-only local evidence for offline past-case prompts, not clinical rules.

Keep referral/interview observations separate. Do not infer dates, units,
normality, diagnoses, current medicine use or a clinically valid expiry.
"""
import datetime as dt
import hashlib
import json

import interview
import pathology_records
import records
import report


def _date(value):
    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y'):
        try:
            return dt.datetime.strptime(str(value), fmt).date()
        except ValueError:
            pass
    return None


def build(conn, patient, today=None):
    import api
    today = today or dt.date.today()
    pid = patient['id']
    saved = records.exists(conn, pid, 'interview.json')
    record = interview.load(conn, patient) if saved else {
        'header': {}, 'meds': [], 'other_meds': [], 'details': {},
        'conditions': '', 'obs': [], 'pathology': [], 'notes': '', 'mobility': ''}
    pathology = pathology_records.load(conn, patient)
    evidence, gaps = [], []

    def add(eid, kind, text, *, eligible=True, date='', **extra):
        if not str(text).strip():
            return
        parsed = _date(date)
        flags = []
        if not parsed:
            flags.append('Date not established')
        elif parsed > today:
            flags.append('Future date: check original')
            eligible = False
        item = dict(id=eid, kind=kind, text=text, date=date,
                    age_days=(today-parsed).days if parsed else None,
                    flags=flags, eligible=eligible, **extra)
        evidence.append(item)

    confirmed = records.get_json(conn, pid, 'confirmed_meds.json')
    current = confirmed is not None and api.confirmed_medicines_current(conn, patient)
    bound = bool(current and confirmed.get('medicine_snapshot_sha256'))
    if confirmed is not None and not current:
        gaps.append('Medicine confirmation is stale; review the current interview and confirm again')
    elif not current:
        gaps.append('Medicines have not been confirmed')
    elif not bound:
        gaps.append('Legacy medicine confirmation has no full identity snapshot binding; re-review it')
    meds = []
    # Read current rows, never silently substitute an old confirmed list.
    for section in ('meds', 'other_meds'):
        for n, row in enumerate(record.get(section, [])):
            if not row or not row[0].strip():
                continue
            meta = record.get('details', {}).get(section, [])
            meta = meta[n] if n < len(meta) else {}
            state = meta.get('use_status', '')
            eligible = state != 'not_using'
            if eligible:
                meds.append(row[0])
            add(section+':'+str(n), 'medicine', row[0], eligible=eligible,
                use_status=state or 'unknown', item_id=meta.get('item_id', ''),
                reference=meta.get('reference'),
                verification='interview identity snapshot matches confirmed-list source; review row use' if bound else
                             'current interview listing, use requires review',
                source='interview.json/'+section+'/'+str(n))
    if not meds:
        gaps.append('No current interview medicine rows available')
    details=record.get('details', {})
    dimensional=any(details.get(k+'_'+v) for k in ('height','weight','bmi') for v in ('referral','actual'))
    for n, row in enumerate(record.get('obs', [])):
        for column, version in ((1, 'referral'), (2, 'interview')):
            if len(row) <= column or not row[column].strip():
                continue
            # Original referral value remains visible but is not ranked alongside
            # a newer interview value. Never assert that two values agree.
            add('obs:'+str(n)+':'+version, 'observation', row[0]+': '+row[column],
                eligible=(column == 2 or len(row) < 3 or not row[2].strip()) and not (row[0]=='Height / weight / BMI' and dimensional),
                verification=version+' text, date/units not independently established',
                source='interview.json/obs/'+str(n)+'/'+str(column))
    for key in ('height','weight','bmi'):
        for version in ('referral','actual'):
            value=details.get(key+'_'+version, '')
            use_referral=bool(details.get(key+'_as_listed') or not details.get(key+'_actual'))
            add('details:'+key+':'+version, 'observation', key.title()+': '+value if value else '',
                eligible=(version=='referral') == use_referral,
                verification='referral value explicitly used as listed' if version=='referral' and details.get(key+'_as_listed') else version+' text',
                source='interview.json/details/'+key+'_'+version)
    for key,label in interview.SYMPTOMS.items():
        if details.get(key) in ('no','not_asked'):
            add('details:'+key, 'interview detail', label+': '+details[key]+(' | '+details[key+'_details'] if details.get(key+'_details') else ''),
                verification='recorded structured answer, not diagnosis inference', source='interview.json/details/'+key)
    # Structured interview detail wording uses the existing report composer.
    # Exclude the observation table so its original versions stay distinct.
    detail_record = dict(record, obs=[], mobility='')
    for n, line in enumerate(report.observations(detail_record).splitlines()):
        add('interview_detail:'+str(n), 'interview detail', line,
            verification='recorded interview detail', source='interview.json/details')
    for key, kind in (('conditions', 'conditions'), ('notes', 'interview notes'), ('concerns','interview concerns'), ('mobility', 'mobility')):
        add(key, kind, record.get(key, ''), verification='recorded text, not a diagnosis inference', source='interview.json/'+key)
    structured_keys = {(r['test'].strip().casefold(), r['value'].strip().casefold(), _date(r['sample_date']))
                       for r in pathology['records'] if r['sample_date']}
    for n, row in enumerate(record.get('pathology', [])):
        if not any(row):
            continue
        duplicate = (row[0].strip().casefold(), row[1].strip().casefold(), _date(row[2])) in structured_keys
        add('legacy_pathology:'+str(n), 'legacy pathology', ' | '.join(row), date=row[2],
            eligible=not duplicate, unit='', reference_interval='',
            verification='UNVERIFIED legacy text; confirm against original',
            source='interview.json/pathology/'+str(n))
    import pathology_values
    for row in pathology['records']:
        audit = pathology['verification'].get(row['id'], {})
        verified = (row['verified'] and isinstance(audit, dict) and
                    isinstance(audit.get('verified_by'), str) and len(audit['verified_by'].strip()) >= 3 and
                    isinstance(audit.get('verified_at'), str))
        if verified:
            try: dt.datetime.fromisoformat(audit['verified_at'])
            except ValueError: verified = False
        # The verified comment is the pharmacist's own saved wording; include it in the
        # literal match text. Never interpret the numeric result itself.
        text = row['test']+': '+row['value']
        if row['comment'].strip(): text += ' | '+row['comment'].strip()
        add('pathology:'+row['id'], 'pathology', text, date=row['sample_date'],
            unit=row['unit'], reference_interval=row['reference_interval'], comment=row['comment'],
            verification='named pharmacist verified' if verified else 'UNVERIFIED: check original',
            source=row['source'], test=row['test'], value=row['value'],
            structured=pathology_values.structure(row['value'], row['reference_interval']) or {},
            verified_by=audit['verified_by'] if verified else '',
            verified_at=audit['verified_at'] if verified else '')
        item = evidence[-1] if evidence and evidence[-1]['id']=='pathology:'+row['id'] else None
        if item:
            for key, label in (('unit','Units missing'), ('source','Source missing'), ('reference_interval','Reference interval not recorded')):
                if not row[key].strip(): item['flags'].append(label)
    for e in evidence:
        if e['kind'] in ('pathology', 'legacy pathology', 'observation'):
            if e['flags'] or e['verification'].startswith('UNVERIFIED'):
                gaps.append(e['id']+': '+', '.join(e['flags']+[e['verification']]))
    gaps.append('No clinical expiry inferred: review sample dates and original notes for relevance, negation and history')
    age = record['header'].get('age', '')
    if not age:
        born = _date(dict(patient).get('dob', ''))
        if born and born <= today:
            age = today.year-born.year-((today.month,today.day)<(born.month,born.day))
    if not age:
        gaps.append('Age not established')
    eligible = [e for e in evidence if e['eligible']]
    # Original eMIMS records are part of the revision key, but old/unbound text
    # must not boost patient-specific suggestion scores.
    interaction_files = {name: records.revision(conn,pid,name) for name in
                         sorted(records.names_like(conn,pid,'MIMS interactions'))}
    import steps
    interaction_text=[]
    for name in interaction_files:
        if steps.interactions_result_current(conn,patient,name):
            text=records.get(conn,pid,name).decode('utf-8',errors='replace')
            add('interaction:'+interaction_files[name], 'eMIMS result', text,
                verification='exact stored result bound to current confirmed list; interpret original wording', source=name)
            interaction_text.append(text)
    if not interaction_text:
        gaps.append('No exact current-list-bound eMIMS result used; older/unbound files are not treated as current')
    revision = {'interview': records.revision(conn,pid,'interview.json'),
                'pathology': pathology['revision'],
                'confirmed_meds': records.revision(conn,pid,'confirmed_meds.json'),
                'interaction_files': interaction_files}
    context = dict(evidence_version=1, age=age, sex=dict(patient).get('sex',''), meds=meds,
                   conditions=record.get('conditions',''),
                   obs='\n'.join(e['text'] for e in eligible if e['kind'] not in ('medicine','pathology','legacy pathology','conditions')),
                   labs=[e['text'] for e in eligible if e['kind'] in ('pathology','legacy pathology')],
                   interactions='\n'.join(interaction_text), evidence=evidence, context_gaps=gaps,
                   source_revisions=revision, medicine_confirmation_current=current,
                   checked_on=today.isoformat())
    context['context_snapshot_sha256'] = fingerprint(context)
    return context


def fingerprint(context):
    value = {k:v for k,v in context.items() if k != 'context_snapshot_sha256'}
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',',':')).encode('utf-8')).hexdigest()
