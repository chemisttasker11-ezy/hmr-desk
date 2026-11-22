"""Bind pharmacist sign-off to an exact, stable, approved DOCX/PDF pair.

Status changes do not constitute clinical review. An explicit named pharmacist
must choose a generated revision and confirm they reviewed its findings.
No prescribing, automatic transmission, or claim submission happens here.
"""
import hashlib
import json
import re
from pathlib import Path

import interview
import jobs
import records
import pathology_records
import template_report_builder


def digest(file):
    return hashlib.sha256(Path(file).read_bytes()).hexdigest()


def source_snapshot(conn, patient):
    """Hash original referral/pathology sources, excluding generated reports."""
    folder = jobs.patient_folder(patient).resolve()
    candidates = []
    for name in ('referral_source.json', 'referral.pdf'):
        candidates.append(folder / name)
    candidates.extend(sorted(
        p for p in folder.iterdir() if p.is_file() and 'referral' in p.stem.lower() and p.suffix.lower() == '.pdf'
    ))
    pathology = folder / 'Pathology'
    if pathology.is_dir():
        candidates.extend(sorted(pathology.glob('*.pdf')))
    result = {}
    stored = records.get(conn, patient['id'], 'pathology_sources.json')
    if stored is not None: result['pathology_sources.json'] = hashlib.sha256(stored).hexdigest()
    for file in candidates:
        if not file.exists():
            continue
        if file.is_symlink() or not file.is_file() or not file.resolve().is_relative_to(folder):
            raise ValueError('Unsafe clinical source path')
        relative = file.relative_to(folder).as_posix()
        result[relative] = digest(file)
    return dict(sorted(result.items()))


def clinical_snapshot_hash(conn, patient, contract=None):
    """Canonical read-only source snapshot. Never edits legacy JSON."""
    import clinical_snapshot
    folder = jobs.patient_folder(patient)
    spec = records.get_json(conn, patient['id'], 'report_spec.json') or {}
    source = folder / 'referral_source.json'
    provenance = json.loads(source.read_text(encoding='utf-8')) if source.is_file() else {}
    canonical = clinical_snapshot.canonical(
        dict(patient), interview.load(conn, patient),
        pathology_records.load(conn, patient), spec, provenance, source_snapshot(conn, patient),
        contract=contract or clinical_snapshot.CONTRACT_CURRENT
    )
    return clinical_snapshot.digest(canonical)


def clinical_snapshot_matches(conn, patient, stored):
    """Compare stored build/sign-off evidence with the current record, fail closed.

    A truly absent marker means evidence written before the GP/clinic detail keys
    existed: compared with the legacy contract (see clinical_snapshot). A present
    marker must be exactly the integer 2 (the only value any build writes); null,
    0, 1, 4, true, strings and anything else fail. Nothing is rewritten.
    """
    import clinical_snapshot
    if not isinstance(stored, dict) or not isinstance(stored.get('clinical_snapshot_sha256'), str):
        return False
    if 'clinical_snapshot_contract' not in stored:
        contract = clinical_snapshot.CONTRACT_LEGACY
    else:
        contract = stored['clinical_snapshot_contract']
        if isinstance(contract, bool) or not isinstance(contract, int) or contract not in (clinical_snapshot.CONTRACT_CURRENT, clinical_snapshot.CONTRACT_FIELD_REVIEW):
            return False
    return stored['clinical_snapshot_sha256'] == clinical_snapshot_hash(conn, patient, contract)


def legacy_gp_block_changed(conn, patient, stored):
    """Legacy evidence (no marker) never digested the clinic line. The report spec that
    build evidence binds does hold the GP block as printed, so a record that no longer
    produces that block (and was not knowingly kept) is drift the digest cannot show."""
    if not isinstance(stored, dict) or 'clinical_snapshot_contract' in stored:
        return False
    import report
    spec = records.get(conn, patient['id'], 'report_spec.json')
    if spec is None:
        return False  # the spec hash comparison already reports a missing or changed spec
    return 'doctor' in report.unresolved_demographics(conn, patient, json.loads(spec.decode('utf-8-sig')))


def generated_versions(conn, patient):
    """Only job-generated, auditable files in the patient's own folder."""
    root = jobs.patient_folder(patient).resolve()
    rows = conn.execute(
        "SELECT id,ts,detail FROM events WHERE patient_id=? AND type='report_build' ORDER BY id DESC",
        (patient['id'],)
    ).fetchall()
    output = []
    for event in rows:
        try:
            detail = json.loads(event['detail'] or '{}')
            filename = detail.get('file', '')
            if not isinstance(filename, str) or Path(filename).name != filename or not filename.lower().endswith('.docx'):
                continue
            file = (root / filename).resolve()
            if file.parent != root or not file.is_file():
                continue
            actual = digest(file)
            pdf = file.with_suffix('.pdf')
            pdf_current = pdf.is_file() and digest(pdf) == detail.get('pdf_sha256', '')
            verified = bool(re.fullmatch(r'[a-f0-9]{64}', detail.get('sha256', ''))) and actual == detail.get('sha256')
            output.append({
                'event_id': event['id'], 'created_at': event['ts'],
                'file': filename, 'sha256': actual,
                'pdf_exists_and_matches': bool(pdf_current),
                'document_matches_build': verified,
                'template_approved_at_build': detail.get('template_approved') is True,
                'template_version': detail.get('template_version', ''),
            })
        except (OSError, ValueError, TypeError, KeyError):
            continue
    return output


def _find_build(conn, patient, filename):
    for event in conn.execute(
        "SELECT id,detail FROM events WHERE patient_id=? AND type='report_build' ORDER BY id DESC",
        (patient['id'],)
    ):
        detail = json.loads(event['detail'] or '{}')
        if detail.get('file') == filename:
            return detail
    raise ValueError('Select a report built by this HMR Desk installation')


def consent_for_approval(record):
    """Check the interview's explicit signed and dated consent attestation.

    This accepts documented paper consent as well as app-signed consent; it does not
    infer consent from the existence of a PDF, a patient's title or a blank flag.
    Validation here is independent of the desktop checklist.
    """
    import datetime as dt
    consent = record.get('consent') if isinstance(record, dict) else None
    if not isinstance(consent, dict) or consent.get('signed') is not True:
        return False
    try:
        date = consent.get('date')
        if not isinstance(date, str) or not date:
            return False
        dt.date.fromisoformat(date)
    except (ValueError, TypeError):
        return False
    if consent.get('by') == 'patient':
        return True
    if consent.get('by') != 'authorised':
        return False
    relationship = consent.get('relationship')
    return (type(relationship) is int and 1 <= relationship <= 5
            and isinstance(consent.get('authorised_name'), str)
            and bool(consent['authorised_name'].strip()))


def check_approval(conn, patient, body):
    if not isinstance(body, dict) or set(body) != {
        'action', 'report_file', 'report_sha256', 'reviewer', 'clinical_reviewed'
    } or body['action'] != 'signed_off' or body['clinical_reviewed'] is not True:
        raise ValueError('Explicit pharmacist review and selected report version are required')
    reviewer = body['reviewer']
    filename = body['report_file']
    sha = body['report_sha256']
    if not isinstance(reviewer, str) or not (3 <= len(reviewer.strip()) <= 150):
        raise ValueError('Pharmacist reviewer name is required')
    if not isinstance(filename, str) or Path(filename).name != filename or filename.lower().endswith('.docx') is False:
        raise ValueError('Invalid report revision filename')
    if not isinstance(sha, str) or not re.fullmatch(r'[a-f0-9]{64}', sha):
        raise ValueError('Invalid report checksum')
    detail = _find_build(conn, patient, filename)
    if not detail.get('template_approved') or not detail.get('pdf_sha256'):
        raise ValueError('An owner-approved Word and matching PDF pair must be built before clinical sign-off')
    template, approved = template_report_builder.approved_template(template_report_builder.active_template_root())
    if detail.get('template_sha256') != approved['sha256']:
        raise ValueError('Approved template changed since report generation; rebuild first')
    if detail.get('source_files_sha256') != source_snapshot(conn, patient):
        raise ValueError('Original referral or pathology source changed since report generation')
    if not clinical_snapshot_matches(conn, patient, detail):
        raise ValueError('Clinical source contract changed since report generation; rebuild')
    root = jobs.patient_folder(patient).resolve()
    file = (root / filename).resolve()
    if file.parent != root or not file.is_file() or digest(file) != sha or sha != detail.get('sha256'):
        raise ValueError('Word report has changed since it was built')
    pdf = file.with_suffix('.pdf')
    if pdf.parent != root or not pdf.is_file() or digest(pdf) != detail['pdf_sha256']:
        raise ValueError('Matching PDF has changed or is missing')
    spec_bytes = records.get(conn, patient['id'], 'report_spec.json')
    if spec_bytes is None or hashlib.sha256(spec_bytes).hexdigest() != detail.get('report_spec_sha256'):
        raise ValueError('Report content changed since it was built; rebuild and review')
    if interview.revision(conn, patient) != detail.get('interview_revision'):
        raise ValueError('Interview changed after report; refresh and rebuild')
    if pathology_records.revision(conn, patient) != detail.get('pathology_revision'):
        raise ValueError('Pathology changed after report; refresh and rebuild')
    # Current builds record interaction evidence as part of their source provenance.
    # Preserve legacy report compatibility, but never sign a newer report whose recorded
    # interaction evidence changed after the pharmacist reviewed the generated document.
    if detail.get('interactions_evidence_sha256'):
        import interaction_scope
        if detail['interactions_evidence_sha256'] != interaction_scope.evidence_digest(conn, patient):
            raise ValueError('Interaction evidence changed after report generation; rebuild and review before sign-off')
    import report
    open_blocks = report.unresolved_demographics(conn, patient, json.loads(spec_bytes.decode('utf-8-sig')))
    if open_blocks:
        raise ValueError('Report ' + ', '.join(sorted(open_blocks)) + ' differs from the patient record; replace it or keep it as written before sign-off')
    if report.held_actions(conn, patient):
        raise ValueError('Held medicine recommendations are unhandled; handle them and rebuild before sign-off')
    import reconciliation
    saved_review = records.get_json(conn, patient['id'], 'reconciliation_review.json') or {}
    current_interview = interview.load(conn, patient)
    if not consent_for_approval(current_interview):
        raise ValueError('Signed, dated patient consent must be recorded before report sign-off')
    review_status = reconciliation.review_status(current_interview, saved_review)
    if not review_status['reviewed']:
        raise ValueError('Medicine reconciliation must be acknowledged for the current interview before sign-off')
    return {
        'report_file': filename,
        'report_sha256': sha,
        'pdf_sha256': detail['pdf_sha256'],
        'report_spec_sha256': detail['report_spec_sha256'],
        'interview_revision': detail['interview_revision'],
        'pathology_revision': detail['pathology_revision'],
        'template_sha256': detail['template_sha256'],
        'template_version': detail['template_version'],
        'source_files_sha256': detail['source_files_sha256'],
        'clinical_snapshot_sha256': detail['clinical_snapshot_sha256'],
        # Preserve interaction evidence that was approved at the report build.
        # Without it the later "report sent" transition cannot detect a
        # changed interaction result after signing.
        **({'interactions_evidence_sha256': detail['interactions_evidence_sha256']}
           if detail.get('interactions_evidence_sha256') else {}),
        **({'clinical_snapshot_contract': detail['clinical_snapshot_contract']}
           if 'clinical_snapshot_contract' in detail else {}),
        'reviewer': reviewer.strip(),
        'medicine_review_hash': review_status['source_hash'],
        'clinical_reviewed': True,
    }


def check_sent(conn, patient):
    """A report cannot be marked sent if its signed bytes or sources changed."""
    last = conn.execute(
        "SELECT detail FROM events WHERE patient_id=? AND type='signed_off' ORDER BY id DESC LIMIT 1",
        (patient['id'],)
    ).fetchone()
    if not last:
        raise ValueError('No approved, pharmacist-signed report version exists')
    evidence = json.loads(last['detail'] or '{}')
    folder = jobs.patient_folder(patient)
    file = (folder / evidence.get('report_file', '')).resolve()
    if file.parent != folder.resolve() or not file.is_file() or digest(file) != evidence.get('report_sha256'):
        raise ValueError('Signed Word report version is no longer intact')
    pdf = file.with_suffix('.pdf')
    if not pdf.is_file() or digest(pdf) != evidence.get('pdf_sha256'):
        raise ValueError('Signed PDF version is no longer intact')
    if hashlib.sha256(records.get(conn, patient['id'], 'report_spec.json') or b'').hexdigest() != evidence.get('report_spec_sha256'):
        raise ValueError('Report was edited after sign-off')
    if interview.revision(conn, patient) != evidence.get('interview_revision'):
        raise ValueError('Interview was edited after sign-off')
    if pathology_records.revision(conn, patient) != evidence.get('pathology_revision'):
        raise ValueError('Pathology was edited after sign-off')
    if evidence.get('source_files_sha256') != source_snapshot(conn, patient):
        raise ValueError('Original source files changed after sign-off')
    if not clinical_snapshot_matches(conn, patient, evidence):
        raise ValueError('Clinical source contract was changed after signing')
    if evidence.get('interactions_evidence_sha256'):
        import interaction_scope
        if interaction_scope.evidence_digest(conn, patient) != evidence['interactions_evidence_sha256']:
            raise ValueError('Interaction evidence changed after sign-off; review and sign a new report')
    if legacy_gp_block_changed(conn, patient, evidence):
        raise ValueError('GP details changed after signing')
    import reconciliation
    current = reconciliation.digest(interview.load(conn, patient))
    if not evidence.get('medicine_review_hash') or current != evidence['medicine_review_hash']:
        raise ValueError('Medicine reconciliation is stale after sign-off')
    return True
