"""Saved-record integration across the referral-to-report flow.

Scope, stated plainly: this is a saved-record integration test. The confirmed
referral facts are seeded directly as referral_source.json clinical_review
(exactly what the pharmacist confirmation step writes); OCR/PDF extraction is
not exercised here. Report refresh is asserted at the revision/digest level
and a real DOCX export is generated and inspected for the saved synthetic
content. OCR-to-export proof is a separate, larger regression.

What it does cover, in order, through the real engine/API surface with
synthetic content only: confirmed referral prefill -> interview save ->
medicine confirmation via POST /api/patients/<id>/meds (snapshot digest and
interview-usage reconciliation enforced) -> verified pathology save ->
observation checks -> report refresh -> staleness invalidation.
"""
import datetime as dt
import json

import api
import candidate_checks as cc
import db
import interview
import pathology_records
import records
import report

TODAY = dt.date(2026, 11, 17)


def _patient(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'BASE', str(tmp_path / 'workspace'))
    monkeypatch.setattr(db, 'DATA_DIR', str(tmp_path / 'userdata'))
    folder = tmp_path / 'workspace' / 'TO SORT' / 'Synthetic'
    folder.mkdir(parents=True)
    (folder / 'referral.pdf').write_bytes(b'%PDF- synthetic no patient identifiers')
    conn = db.connect(str(tmp_path / 'userdata' / 'hmr.db'))
    with conn:
        pid = conn.execute("INSERT INTO patients(key,name,folder) VALUES (?,?,?)",
                           ('synthetic', 'Synthetic Patient', 'TO SORT/Synthetic')).lastrowid
    return conn, conn.execute('SELECT * FROM patients WHERE id=?', (pid,)).fetchone(), folder


def _confirm_referral(folder):
    reviewed = {'confirmed': True, 'source_page': 1, 'reviewed_by': 'Synthetic Pharmacist',
                'allergies_status': 'explicit_none',
                'conditions': 'Synthetic type 2 diabetes', 'medicines': 'Synthetic Jardiance 25 mg tablet',
                'observations': 'Synthetic observation', 'allergies': ''}
    (folder / 'referral_source.json').write_text(json.dumps({'clinical_review': reviewed}))


def test_referral_to_report_flow_stays_consistent(tmp_path, monkeypatch):
    monkeypatch.setattr(interview, 'referral_text', lambda folder: (None, []))
    conn, patient, folder = _patient(tmp_path, monkeypatch)
    _confirm_referral(folder)

    # 1. Confirmed referral facts prefill the interview; unconfirmed never would.
    data = interview.blank(conn, patient)
    assert data['conditions'] == 'Synthetic type 2 diabetes'
    assert 'explicitly documented' in data['allergies']
    data['meds'] = [['Synthetic Jardiance 25 mg tablet', 'one daily', 'one daily', '', '']]
    data['details']['meds'] = [{'packed': '', 'as_instructed': False, 'use_status': 'taking',
                                'use_reason': '', 'use_details': ''}]
    data['obs'] = [['BP', '', '120/80']]
    data['notes'] = 'Synthetic interview note'
    interview.validate(data)
    data['revision'] = records.revision(conn, patient['id'], 'interview.json')
    interview.save(conn, patient, data)
    conn.commit()

    # 2. Medicine confirmation through the real API contract: read the current
    # snapshot digest first, then confirm against it (stale digests 400).
    get_status, proposal = api.handle(conn, 'GET', '/api/patients/%s/meds' % patient['id'], {}, None)
    assert get_status == 200
    status, confirmed = api.handle(conn, 'POST', '/api/patients/%s/meds' % patient['id'], {},
                                   {'meds': [['Synthetic Jardiance 25 mg tablet', 'one daily']],
                                    'allergies': [],
                                    'medicine_snapshot_sha256': proposal['medicine_snapshot_sha256'],
                                    'interview_usage': proposal['interview_usage']})
    assert status == 200, confirmed
    assert confirmed['confirmed_at']

    # 3. Verified pathology row: eGFR below its laboratory-stated interval.
    row = dict(id='c' * 32, test='eGFR', value='28', unit='mL/min/1.73m2',
               reference_interval='60-120', sample_date='2026-11-10',
               source='synthetic-lab.pdf page 2', verified=True, comment='')
    pathology_records.save(conn, patient, {'revision': pathology_records.revision(conn, patient),
                                           'records': [row]}, reviewer='Synthetic Reviewer')

    # 4. Observation checks reflect the saved, verified evidence.
    result = cc.for_patient(conn, patient)
    obs = next(o for o in result['observations'] if o['evidence_id'] == 'pathology:' + 'c' * 32)
    assert obs['status'] == 'below_stated_interval'
    assert obs['value_exact'] == '28' and obs['interval_low_exact'] == '60'
    assert obs['applicability'] == 'unestablished'
    assert result['review_status'] == 'pharmacist_review_required'

    # 5. Report refresh derives from the same interview/pathology revisions.
    spec = {key: '' for key in ('allergies', 'assess_date', 'conditions', 'dear', 'doctor',
                                'followup', 'intro', 'name', 'obs', 'out', 'path_date', 'patient',
                                'reason', 'report_date', 'thanks')}
    spec.update(meds=[], otc=[], path=[], ceased=[], issues=[])
    records.put_json(conn, patient['id'], 'report_spec.json', spec)
    refreshed = report.refresh(conn, patient)
    conn.commit()
    assert refreshed['interview_revision'] == records.revision(conn, patient['id'], 'interview.json')
    assert refreshed['pathology_revision'] == pathology_records.revision(conn, patient)
    assert refreshed['medicine_snapshot_sha256']

    # 6. Evidence change after confirmation marks the confirmation stale.
    data['notes'] = 'Synthetic interview note updated after confirmation'
    data['revision'] = records.revision(conn, patient['id'], 'interview.json')
    interview.save(conn, patient, data)
    conn.commit()
    assert not api.confirmed_medicines_current(conn, patient)
    stale = cc.for_patient(conn, patient)
    assert stale['review_status'] == 'pharmacist_review_required'

    # 7. A real export is generated from the refreshed spec and its content
    # carries the saved evidence, not just structure fingerprints. The stale
    # confirmation from step 6 does not block rendering the already-refreshed
    # spec (render takes the validated spec as given; refresh is what guards).
    import local_report_builder
    from docx import Document
    out = tmp_path / 'Synthetic Flow Report.docx'
    assert local_report_builder.render(refreshed, out) == out
    assert out.exists() and out.stat().st_size > 0
    try:
        local_report_builder.render(refreshed, out)
        raise AssertionError('render must refuse to overwrite an existing report')
    except FileExistsError:
        pass
    doc = Document(str(out))
    headings = [p.text for p in doc.paragraphs if p.style.name.startswith('Heading')]
    paragraphs = [p.text for p in doc.paragraphs]
    assert 'Home Medicines Review' in paragraphs
    assert 'Patient details' in headings
    assert 'Current medicines' in headings, headings
    assert 'Pathology' in headings, headings
    assert 'Medication-related findings and recommendations' in headings
    # Table content matches the saved synthetic evidence exactly.
    tables = [[cell.text for row in t.rows for cell in row.cells] for t in doc.tables]
    meds_table = next(t for t in tables if 'Actual use' in t)
    assert 'Synthetic Jardiance 25 mg tablet' in meds_table
    assert any('one daily' in cell for cell in meds_table), meds_table
    path_table = next(t for t in tables if 'Reference range' in t)
    assert 'eGFR' in path_table and '28' in path_table
    assert 'mL/min/1.73m2' in path_table and '60-120' in path_table
    assert any('synthetic-lab.pdf' in cell for cell in path_table), path_table
    conn.close()
