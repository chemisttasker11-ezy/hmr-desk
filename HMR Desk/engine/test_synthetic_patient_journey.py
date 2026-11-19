"""One fictional patient's referral -> interview -> report -> approval and sent workflow.

Only synthetic data and a synthetic approved-layout *simulation*. This cannot
establish actual owner template fidelity, pharmacist clinical accuracy or a real
Windows 11 user acceptance test. Run after offline PDF converter is installed.
"""
import hashlib
import json
from pathlib import Path

import fitz
import pytest
from docx import Document

import api
import db
import interview
import jobs
import pathology_records
import reconciliation
import records
import referral_entry
import report
import report_auth
import report_status
import template_report_builder
from test_template_report_builder import make_template


def _patient(conn, pid):
    return conn.execute("SELECT * FROM patients WHERE id=?", (pid,)).fetchone()


def _act(conn, pid, name, **fields):
    result = api.action(conn, _patient(conn, pid), {'action': name, **fields})
    conn.commit()
    return result


def _referral(path):
    """Real, searchable 1-page fictional referral; parser is not mocked."""
    lines = [
        'Home Medicines Review Referral',
        'Patient Details',
        'Name: Synthetic Journey',
        'Date of birth: 01/02/1950',
        'Address: 12 Fictional Road',
        'Phone: 0412000000',
        'General Practitioner Details',
        'Name: Dr Example',
        'Current medications',
        'Synthetic medicine 5 mg tablet',
        'One tablet daily',
        'Known allergies: nil documented',
        'Medical history: fictional chronic condition',
        'Home Medicines Review requested',
        'Please review the medicines and return the HMR report.',
    ]
    pdf = fitz.open()
    page = pdf.new_page()
    for i, line in enumerate(lines):
        page.insert_text((42, 50 + 23 * i), line, fontsize=11)
    pdf.save(str(path))
    pdf.close()


def test_synthetic_pdf_referral_to_signed_sent_report(tmp_path, monkeypatch):
    root = tmp_path / 'workspace'
    root.mkdir()
    userdata = tmp_path / 'userdata'
    userdata.mkdir()
    monkeypatch.setattr(db, 'BASE', str(root))
    monkeypatch.setattr(db, 'DATA_DIR', str(userdata))
    monkeypatch.setenv('HMR_DB', str(userdata / 'hmr.db'))

    # The manifest is deliberately artificial and scoped to a temporary QA root;
    # never register this template as the real owner's approved layout.
    templates = tmp_path / 'synthetic-qa-template'
    templates.mkdir()
    make_template(templates / 'approved-hmr.docx')
    template = templates / 'approved-hmr.docx'
    (templates / 'approved-hmr.json').write_text(json.dumps({
        'version': 'synthetic-journey-only',
        'sha256': hashlib.sha256(template.read_bytes()).hexdigest(),
        'approved_by': 'Synthetic QA only',
        'approved_on': '2026-11-20',
    }), encoding='utf-8')
    monkeypatch.setattr(template_report_builder, 'active_template_root', lambda: templates)

    source = tmp_path / 'fictional-referral.pdf'
    _referral(source)
    original = source.read_bytes()
    conn = db.connect()
    try:
        # REFERRAL REVIEW: real PDF reader and parser, explicit review of any
        # unusual layout. Do not infer clinical information from a surname.
        row = referral_entry.review(conn, [str(source)])['rows'][0]
        assert row['status'] in ('review', 'manual'), row
        fields = {'name': 'Synthetic Journey', 'dob': '01/02/1950',
                  'gp': 'Dr Example', 'sex': 'F',
                  'phone': '0412000000', 'referral_date': '2026-11-19'}
        clinical = {
            'confirmed': True, 'allergies_status': 'explicit_none',
            'reviewed_by': 'Synthetic Pharmacist', 'source_page': 1,
            'conditions': 'Fictional chronic condition',
            'allergies': '', 'medicines': 'Synthetic medicine 5 mg tablet, one daily',
            'observations': '',
        }
        pid = referral_entry.commit(
            conn, row['token'], fields,
            manual_referral=row['status'] == 'manual', clinical=clinical
        )['patient_id']
        p = _patient(conn, pid)
        folder = jobs.patient_folder(p)
        assert (folder / 'referral.pdf').read_bytes() == original
        assert source.read_bytes() == original
        assert referral_entry.review(conn, [str(source)])['rows'][0]['status'] == 'duplicate'

        # BOOKING / INTERVIEW: consent is entered once, in the interview.
        _act(conn, pid, 'book_phone', date='2026-11-25', time='09:00', end='10:00')
        p = _patient(conn, pid)
        data = interview.load(conn, p)
        assert data['header']['name'] == 'Synthetic Journey'
        data['meds'] = [['Synthetic medicine 5 mg tablet', 'one daily', 'one daily', '', '']]
        data['details']['meds'] = [{'packed': '', 'as_instructed': False,
                                   'use_status': 'taking', 'use_reason': '', 'use_details': ''}]
        data['notes'] = 'Synthetic pharmacist interview, documented without AI.'
        data['consent'] = {'signed': True, 'date': '2026-11-25', 'by': 'patient',
                           'relationship': 0, 'authorised_name': ''}
        data['revision'] = interview.revision(conn, p)
        interview.save(conn, p, data)
        conn.commit()
        _act(conn, pid, 'visited', date='2026-11-25')

        # MEDICINES: confirm the API's current snapshot, never a stale hash.
        route = '/api/patients/%s/meds' % pid
        code, medicine = api.handle(conn, 'GET', route, {}, None)
        assert code == 200, medicine
        code, confirmed = api.handle(conn, 'POST', route, {}, {
            'meds': [['Synthetic medicine 5 mg tablet', 'one daily']],
            'allergies': [],
            'medicine_snapshot_sha256': medicine['medicine_snapshot_sha256'],
            'interview_usage': medicine['interview_usage'],
        })
        assert code == 200, confirmed
        _act(conn, pid, 'interactions_manual',
             text='Synthetic interaction review recorded; no live eMIMS assertions.')

        # PATHOLOGY: a verified fictional result with a source/reference interval.
        p = _patient(conn, pid)
        pathology_records.save(conn, p, {
            'revision': pathology_records.revision(conn, p),
            'records': [{
                'id': 'c' * 32, 'test': 'eGFR', 'value': '42',
                'unit': 'mL/min/1.73m2', 'reference_interval': '60-120',
                'sample_date': '2026-11-18', 'source': 'fictional-lab.pdf page 1',
                'verified': True, 'comment': 'Synthetic laboratory finding',
            }],
        }, reviewer='Synthetic Pharmacist')
        conn.commit()

        # REVIEW: explicitly acknowledge the exact current interview medicines.
        p = _patient(conn, pid)
        current = interview.load(conn, p)
        review = reconciliation.acknowledge(
            current, reconciliation.digest(current), 'Synthetic Pharmacist'
        )
        records.put_json(conn, pid, 'reconciliation_review.json', review)
        conn.commit()

        # REPORT: use the real deterministic engine and a local artificial
        # owner-layout simulation. No hardcoded report bytes or forged build event.
        spec = report.start(conn, p)
        spec.update(
            reason='Synthetic review of medicine use',
            intro='Synthetic patient interview completed for regression testing.',
            followup_decision='not_required',
            followup='No additional follow-up planned in this fictional case.',
            issues=[{
                'title': 'Synthetic medicine directions',
                'rec': 'The fictional GP could verify the documented dose.',
                'rationale': 'The fictional record was reviewed for consistency.',
            }],
            needs_review=[],
        )
        report.save(conn, p, spec)
        conn.commit()
        stored = report.load(conn, p)
        assert not report.placeholders(stored), report.placeholders(stored)
        output = jobs.report_build(pid, pdf=True)
        # report_build names the PDF in its message only when a cleanup note is pending, so the PDF is verified from
        # the build event and the file itself below, not from the message text.
        assert output.startswith('Built approved-layout Word draft'), output

        # REAL OUTPUT: inspect both generated files, not merely an event flag.
        events = conn.execute(
            "SELECT detail FROM events WHERE patient_id=? AND type='report_build' ORDER BY id DESC LIMIT 1",
            (pid,),
        ).fetchone()
        assert events, 'No report build event'
        detail = json.loads(events['detail'])
        word = folder / detail['file']
        pdf = word.with_suffix('.pdf')
        assert word.is_file() and pdf.is_file()
        assert hashlib.sha256(word.read_bytes()).hexdigest() == detail['sha256']
        assert hashlib.sha256(pdf.read_bytes()).hexdigest() == detail['pdf_sha256']
        assert detail['template_approved'] and detail['template_version'] == 'synthetic-journey-only'
        document = Document(str(word))
        text = '\n'.join([p.text for p in document.paragraphs] +
                         [cell.text for table in document.tables
                          for r in table.rows for cell in r.cells])
        assert 'Synthetic Journey' in text
        assert 'Synthetic medicine directions' in text
        assert 'eGFR' in text
        with fitz.open(pdf) as rendered:
            pdf_text = '\n'.join(page.get_text() for page in rendered)
            assert 'Synthetic Journey' in pdf_text
            assert rendered.page_count >= 1 and 'Synthetic medicine directions' in pdf_text
        raw = pdf.read_bytes()
        assert raw.startswith(b'%PDF-') and b'%%EOF' in raw[-1024:] and len(raw) >= 1000
        assert not list(folder.glob('.hmr-pdf-*')), 'converter scratch folder left behind'

        # SIGN-OFF: backend checks the actual built pair, review, and consent
        # already saved in interview; no UI-only authorisation assumptions.
        status = report_status.report_status(conn, _patient(conn, pid))
        assert status['status'] == 'current', status
        states = {item['key']: item['state'] for item in status['readiness']['items']}
        assert states == {'consent_recorded': 'met',
                          'medicines_reconciled': 'met', 'demographics_match': 'met'}, states
        _act(conn, pid, 'signed_off', report_file=word.name,
             report_sha256=detail['sha256'], reviewer='Synthetic Pharmacist',
             clinical_reviewed=True)
        assert _patient(conn, pid)['state'] == 'signed_off'
        _act(conn, pid, 'report_sent', date='2026-11-26')
        assert _patient(conn, pid)['state'] == 'sent'

    finally:
        conn.close()

    # REOPEN: report, state, consent, files and signed evidence survive a new
    # database connection after the synthetic application session ends.
    with db.connect() as reopened:
        p = _patient(reopened, pid)
        assert p['state'] == 'sent'
        assert interview.load(reopened, p)['consent']['signed'] is True
        assert report_status.report_status(reopened, p)['signed_version_intact'] is True
