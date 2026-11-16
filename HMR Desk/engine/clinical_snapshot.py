"""Versioned non-destructive clinical data contract for AI-OFF HMR reports.

Adapts historical SQLite/JSON data without rewriting originals. Unverified and
unknown are distinct from pharmacist-confirmed absence. Every derived report
snapshot is bound to exact source revisions and carries no prescribing decisions.
"""
import hashlib
import json
from pathlib import Path

import clinical_review


SCHEMA_VERSION = 1
MAX_ITEMS = 120


def source_state(value, confirmed=False):
    """An empty source does not assert none/normal."""
    if not confirmed:
        return 'unverified' if value else 'unknown'
    return 'confirmed' if value else 'confirmed_empty'


def _text(value, max_chars=20000):
    if value is None:
        return ''
    if not isinstance(value, str) or len(value) > max_chars:
        raise ValueError('Invalid clinical snapshot text')
    return value


def _medicine_rows(record, section):
    rows = record.get(section, [])
    if not isinstance(rows, list) or len(rows) > MAX_ITEMS:
        raise ValueError('Invalid clinical medicine table')
    details = record.get('details', {}).get(section, [])
    if not isinstance(details, list):
        raise ValueError('Invalid actual medicine-use details')
    medicines = []
    for index, row in enumerate(rows):
        if not isinstance(row, list) or len(row) < (5 if section == 'meds' else 4):
            raise ValueError('Invalid medicine row')
        info = details[index] if index < len(details) and isinstance(details[index], dict) else {}
        if section == 'meds':
            drug, directions, actual, indication, comments = row[:5]
        else:
            drug, directions, indication, comments = row[:4]
            actual = ''
        identity = _text(drug).strip()
        medicines.append({
            'row_id': section + ':' + str(index),
            'name': identity,
            'prescribed_or_reported_directions': _text(directions),
            'actual_directions': _text(actual),
            'indication': _text(indication),
            'notes': _text(comments),
            'use_status': _text(info.get('use_status', '')).strip() or 'unknown',
            'as_instructed': info.get('as_instructed') is True,
            'prn_use': _text(info.get('prn_use', '')),
            'use_reason': _text(info.get('use_reason', '')),
            'packed': _text(info.get('packed', '')),
            'verification': 'pharmacist_interview_record' if _text(actual) or
                            info.get('as_instructed') is True else 'unconfirmed_actual_use',
        })
    return medicines


def canonical(identity, interview_record, pathology, report_spec, referral_source=None,
              source_hashes=None):
    if not isinstance(interview_record, dict) or not isinstance(pathology, dict):
        raise ValueError('Invalid clinical snapshot records')
    if not isinstance(identity, dict) or not isinstance(report_spec, dict):
        raise ValueError('Invalid clinical identity or report specifications')
    referral_source = referral_source or {}
    review = referral_source.get('clinical_review', {})
    if not isinstance(review, dict):
        raise ValueError('Invalid referral review')
    reviewed = clinical_review.is_reviewed(review)
    reported_allergy_state = review.get('allergies_status', 'unknown') if reviewed else 'unknown'
    if reported_allergy_state not in ('unknown', 'explicit_none', 'listed'):
        reported_allergy_state = 'unknown'
    medication_use = _medicine_rows(interview_record, 'meds') + _medicine_rows(interview_record, 'other_meds')
    results = pathology.get('records', [])
    verification = pathology.get('verification', {})
    if not isinstance(results, list) or len(results) > MAX_ITEMS or not isinstance(verification, dict):
        raise ValueError('Invalid pathology snapshot')
    tests = []
    for result in results:
        if not isinstance(result, dict):
            raise ValueError('Invalid pathology result')
        rid = _text(result.get('id',''))
        verified = result.get('verified') is True and rid in verification
        tests.append({
            'id': rid, 'test': _text(result.get('test','')),
            'value': _text(result.get('value','')),
            'unit': _text(result.get('unit','')),
            'collection_date': _text(result.get('sample_date','')),
            'source': _text(result.get('source','')),
            'reference_interval': _text(result.get('reference_interval','')),
            'verification': 'named_pharmacist_confirmed' if verified else 'unconfirmed',
            'verified_by': _text(verification.get(rid, {}).get('verified_by','')) if verified else '',
            'verified_at': _text(verification.get(rid, {}).get('verified_at','')) if verified else '',
        })
    issues = report_spec.get('issues', [])
    if not isinstance(issues, list) or len(issues) > MAX_ITEMS:
        raise ValueError('Invalid report findings')
    findings = []
    for i, issue in enumerate(issues):
        if not isinstance(issue, dict):
            raise ValueError('Invalid report finding')
        findings.append({
            'id': str(i),
            'title': _text(issue.get('title','')),
            'action': _text(issue.get('rec','')),
            'rationale': _text(issue.get('rationale','')),
            'status': 'pharmacist_review_required',
        })
    person = {
        'name': _text(identity.get('name','')),
        'dob': _text(identity.get('dob','')),
        'gp': _text(identity.get('gp','')),
        'referral_date': _text(identity.get('referral_date','')),
    }
    if not person['name'].strip():
        raise ValueError('Patient identity is incomplete')
    allergies = _text(interview_record.get('allergies',''))
    return {
        'schema_version': SCHEMA_VERSION,
        'patient_identity': person,
        'referral_source_sha256': _text(referral_source.get('sha256','')),
        'original_sources_sha256': source_hashes or {},
        'allergies': {
            'narrative': allergies, 'confirmed_negative': reported_allergy_state == 'explicit_none',
            'state': reported_allergy_state if reviewed else source_state(allergies),
        },
        'conditions': {'narrative': _text(interview_record.get('conditions','')),
                       'review': source_state(interview_record.get('conditions',''), reviewed)},
        'medication_use': medication_use,
        'pathology': tests,
        'findings': findings,
        'consent': interview_record.get('consent', {}),
    }


def digest(snapshot):
    return hashlib.sha256(json.dumps(snapshot, ensure_ascii=False, sort_keys=True,
                                      separators=(',', ':')).encode('utf-8')).hexdigest()
