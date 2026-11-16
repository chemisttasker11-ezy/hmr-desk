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
import pathology_records
import template_report_builder


def digest(file):
    return hashlib.sha256(Path(file).read_bytes()).hexdigest()


def source_snapshot(patient):
    """Hash original referral/pathology sources, excluding generated reports."""
    folder = jobs.patient_folder(patient).resolve()
    candidates = []
    for name in ('referral_source.json', 'pathology_sources.json', 'referral.pdf'):
        candidates.append(folder / name)
    candidates.extend(sorted(
        p for p in folder.iterdir() if p.is_file() and 'referral' in p.stem.lower() and p.suffix.lower() == '.pdf'
    ))
    pathology = folder / 'Pathology'
    if pathology.is_dir():
        candidates.extend(sorted(pathology.glob('*.pdf')))
    result = {}
    for file in candidates:
        if not file.exists():
            continue
        if file.is_symlink() or not file.is_file() or not file.resolve().is_relative_to(folder):
            raise ValueError('Unsafe clinical source path')
        relative = file.relative_to(folder).as_posix()
        result[relative] = digest(file)
    return dict(sorted(result.items()))


def clinical_snapshot_hash(conn, patient):
    """Canonical read-only source snapshot. Never edits legacy JSON."""
    import clinical_snapshot
    folder = jobs.patient_folder(patient)
    report = jobs.report_spec_path(patient)
    spec = json.loads(report.read_text(encoding='utf-8')) if report.is_file() else {}
    source = folder / 'referral_source.json'
    provenance = json.loads(source.read_text(encoding='utf-8')) if source.is_file() else {}
    canonical = clinical_snapshot.canonical(
        dict(patient), interview.load(conn, patient),
        pathology_records.load(patient), spec, provenance, source_snapshot(patient)
    )
    return clinical_snapshot.digest(canonical)


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
    if detail.get('source_files_sha256') != source_snapshot(patient):
        raise ValueError('Original referral or pathology source changed since report generation')
    if detail.get('clinical_snapshot_sha256') != clinical_snapshot_hash(conn, patient):
        raise ValueError('Clinical source contract changed since report generation; rebuild')
    root = jobs.patient_folder(patient).resolve()
    file = (root / filename).resolve()
    if file.parent != root or not file.is_file() or digest(file) != sha or sha != detail.get('sha256'):
        raise ValueError('Word report has changed since it was built')
    pdf = file.with_suffix('.pdf')
    if pdf.parent != root or not pdf.is_file() or digest(pdf) != detail['pdf_sha256']:
        raise ValueError('Matching PDF has changed or is missing')
    spec = jobs.report_spec_path(patient)
    if not spec.is_file() or digest(spec) != detail.get('report_spec_sha256'):
        raise ValueError('Report content changed since it was built; rebuild and review')
    if interview.revision(root / 'interview.json') != detail.get('interview_revision'):
        raise ValueError('Interview changed after report; refresh and rebuild')
    if pathology_records.revision(pathology_records.file_for(patient)) != detail.get('pathology_revision'):
        raise ValueError('Pathology changed after report; refresh and rebuild')
    import reconciliation
    review_file = root / 'reconciliation_review.json'
    saved_review = json.loads(review_file.read_text(encoding='utf-8')) if review_file.is_file() else {}
    current_interview = interview.load(conn, patient)
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
    if digest(jobs.report_spec_path(patient)) != evidence.get('report_spec_sha256'):
        raise ValueError('Report was edited after sign-off')
    if interview.revision(folder / 'interview.json') != evidence.get('interview_revision'):
        raise ValueError('Interview was edited after sign-off')
    if pathology_records.revision(pathology_records.file_for(patient)) != evidence.get('pathology_revision'):
        raise ValueError('Pathology was edited after sign-off')
    if evidence.get('source_files_sha256') != source_snapshot(patient):
        raise ValueError('Original source files changed after sign-off')
    if evidence.get('clinical_snapshot_sha256') != clinical_snapshot_hash(conn, patient):
        raise ValueError('Clinical source contract was changed after signing')
    import reconciliation
    current = reconciliation.digest(interview.load(conn, patient))
    if not evidence.get('medicine_review_hash') or current != evidence['medicine_review_hash']:
        raise ValueError('Medicine reconciliation is stale after sign-off')
    return True
