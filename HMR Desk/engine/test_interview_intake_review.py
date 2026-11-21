"""Synthetic clinical referral review contract and conservative interview transfer."""
import json

import pytest

import db
import interview
import referral_entry


def test_allergy_explicit_none_requires_source_page_and_pharmacist():
    review = {'conditions':'', 'medicines':'', 'observations':'',
              'allergies':'', 'allergies_status':'explicit_none',
              'source_page':1, 'reviewed_by':'Synthetic Pharmacist', 'confirmed':True}
    assert referral_entry.validate_clinical_review(review,2)['allergies_status'] == 'explicit_none'
    with pytest.raises(ValueError,match='source confirmation'):
        referral_entry.validate_clinical_review({**review,'confirmed':False},2)
    with pytest.raises(ValueError,match='Source page'):
        referral_entry.validate_clinical_review({**review,'source_page':0},2)
    with pytest.raises(ValueError,match='Invalid PDF source page'):
        referral_entry.validate_clinical_review({**review,'source_page':3},2)
    with pytest.raises(ValueError,match='Explicitly no known allergies'):
        referral_entry.validate_clinical_review({**review,'allergies':'Penicillin'},2)


def test_only_confirmed_source_facts_prepopulate_interview(tmp_path,monkeypatch):
    folder = tmp_path / 'workspace' / 'TO SORT' / 'Synthetic'
    folder.mkdir(parents=True)
    monkeypatch.setattr(db,'BASE',str(tmp_path / 'workspace'))
    monkeypatch.setattr(db,'DATA_DIR',str(tmp_path / 'userdata'))
    monkeypatch.setattr(interview,'referral_text',lambda folder:(None,[]))
    conn = db.connect(str(tmp_path / 'userdata' / 'hmr.db'))
    with conn:
        pid=conn.execute("INSERT INTO patients(key,name,folder) VALUES (?,?,?)",
                         ('synthetic','Synthetic Patient','TO SORT/Synthetic')).lastrowid
    patient=conn.execute('SELECT * FROM patients WHERE id=?',(pid,)).fetchone()
    reviewed={'confirmed':False,'source_page':1,'reviewed_by':'Synthetic Pharmacist',
              'allergies_status':'unknown','conditions':'Synthetic condition text',
              'medicines':'Synthetic prescribed medicine only',
              'observations':'Synthetic observation text','allergies':''}
    (folder / 'referral_source.json').write_text(json.dumps({'clinical_review':reviewed}))
    unconfirmed=interview.blank(conn,patient)
    assert unconfirmed['conditions'] == ''
    assert unconfirmed['allergies'] == ''
    assert any('Unconfirmed source material' in x for x in unconfirmed['clarify'])
    reviewed.update(confirmed=True,allergies_status='explicit_none')
    (folder / 'referral_source.json').write_text(json.dumps({'clinical_review':reviewed}))
    confirmed=interview.blank(conn,patient)
    assert confirmed['conditions'] == 'Synthetic condition text'
    assert 'explicitly documented' in confirmed['allergies']
    assert any('Synthetic prescribed medicine only' in x for x in confirmed['clarify'])
    assert any(row[1]=='Synthetic observation text' for row in confirmed['obs'])
    # The confirmed list is reused as one row per line exactly as entered: no split name/directions, no actual use, no status.
    assert confirmed['meds'] == [['Synthetic prescribed medicine only','','','','']]
    assert not confirmed['details']['meds'][0].get('use_status')
    interview.validate(confirmed)
    conn.close()


def test_confirmed_intake_medicines_become_unconfirmed_rows_exactly_as_entered(tmp_path,monkeypatch):
    folder = tmp_path / 'workspace' / 'TO SORT' / 'Synthetic'
    folder.mkdir(parents=True)
    monkeypatch.setattr(db,'BASE',str(tmp_path / 'workspace'))
    monkeypatch.setattr(db,'DATA_DIR',str(tmp_path / 'userdata'))
    monkeypatch.setattr(interview,'referral_text',lambda folder:(None,[]))
    conn = db.connect(str(tmp_path / 'userdata' / 'hmr.db'))
    with conn:
        pid=conn.execute("INSERT INTO patients(key,name,folder) VALUES (?,?,?)",
                         ('synthetic','Synthetic Patient','TO SORT/Synthetic')).lastrowid
    patient=conn.execute('SELECT * FROM patients WHERE id=?',(pid,)).fetchone()
    lines=['Synthetic Medicine A 10 mg tablet - Take one tablet daily','  Synthetic Medicine B 20 mg tablet - Take one tablet nightly  ']
    reviewed={'confirmed':True,'source_page':1,'reviewed_by':'Synthetic Pharmacist','allergies_status':'unknown',
              'conditions':'','allergies':'','observations':'','medicines':'\n'.join(lines)+'\n\n'}
    (folder / 'referral_source.json').write_text(json.dumps({'clinical_review':reviewed}))
    record=interview.blank(conn,patient)
    assert [row[0] for row in record['meds']] == [lines[0],lines[1].strip()]
    assert all(row[1:] == ['','','',''] for row in record['meds'])
    assert len(record['details']['meds']) == 2
    assert all(not meta.get('use_status') and not meta.get('checked') for meta in record['details']['meds'])
    interview.validate(record)
    assert any('Confirmed prescribed referral list' in x for x in record['clarify'])
    assert any('use not confirmed' in x for x in record['sources'])
    # unconfirmed review, existing rows, too many or oversized lines: no rows are made
    reviewed['confirmed']=False
    (folder / 'referral_source.json').write_text(json.dumps({'clinical_review':reviewed}))
    assert interview.blank(conn,patient)['meds'] == []
    reviewed.update(confirmed=True,medicines='\n'.join('Synthetic %d 1 mg' % n for n in range(61)))
    (folder / 'referral_source.json').write_text(json.dumps({'clinical_review':reviewed}))
    assert interview.blank(conn,patient)['meds'] == []
    reviewed.update(medicines='x'*401)
    (folder / 'referral_source.json').write_text(json.dumps({'clinical_review':reviewed}))
    assert interview.blank(conn,patient)['meds'] == []


def test_saved_edits_to_reused_medicine_rows_survive_reopen(tmp_path,monkeypatch):
    folder = tmp_path / 'workspace' / 'TO SORT' / 'Synthetic'
    folder.mkdir(parents=True)
    monkeypatch.setattr(db,'BASE',str(tmp_path / 'workspace'))
    monkeypatch.setattr(db,'DATA_DIR',str(tmp_path / 'userdata'))
    monkeypatch.setattr(interview,'referral_text',lambda folder:(None,[]))
    conn = db.connect(str(tmp_path / 'userdata' / 'hmr.db'))
    with conn:
        pid=conn.execute("INSERT INTO patients(key,name,folder) VALUES (?,?,?)",
                         ('synthetic','Synthetic Patient','TO SORT/Synthetic')).lastrowid
    patient=conn.execute('SELECT * FROM patients WHERE id=?',(pid,)).fetchone()
    reviewed={'confirmed':True,'source_page':1,'reviewed_by':'Synthetic Pharmacist','allergies_status':'unknown',
              'conditions':'','allergies':'','observations':'','medicines':'Synthetic Medicine A - Take daily'}
    (folder / 'referral_source.json').write_text(json.dumps({'clinical_review':reviewed}))
    record=interview.load(conn,patient)
    record['meds'][0][0]='Synthetic Medicine A 10 mg'
    record['meds'][0][1]='Take daily'
    interview.save(conn,patient,record); conn.commit()
    # Change the review text afterwards: a saved interview must not be rebuilt from it.
    reviewed['medicines']='Synthetic Medicine B - Take nightly'
    (folder / 'referral_source.json').write_text(json.dumps({'clinical_review':reviewed}))
    again=interview.load(conn,patient)
    assert [r[:2] for r in again['meds']] == [['Synthetic Medicine A 10 mg','Take daily']]


def test_confirmed_intake_preserves_source_supported_pdf_row_pairing(tmp_path, monkeypatch):
    """Two-column PDF writes names first, directions second; reviewed '-' separators must not erase genuine row cells.

    All medicines, pharmacist, and patient details are synthetic. This test intentionally fails on the starting head.
    """
    import fitz
    folder = tmp_path / 'workspace' / 'TO SORT' / 'Synthetic'
    folder.mkdir(parents=True)
    monkeypatch.setattr(db, 'BASE', str(tmp_path / 'workspace'))
    monkeypatch.setattr(db, 'DATA_DIR', str(tmp_path / 'userdata'))
    rows = [('Lunovex 5mg Tablet', '1 Taplet Daily'),
            ('Fictamol 10mg Capsule', '2 Capsules At night'),
            ('Nuvrala 20mg Tablet', '1 Tablet With meals')]
    pdf = folder / 'referral.pdf'
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 55), 'Medical History', fontsize=11)
    page.insert_text((50, 75), 'Synthetic test only; no personal or clinical facts are confirmed.', fontsize=9)
    page.insert_text((50, 100), 'Current Medications', fontsize=11)
    # Deliberately column-first in PDF text-layer order (not visual reading order).
    for i, (name, _) in enumerate(rows):
        page.insert_text((50, 130 + 22 * i), name, fontsize=10)
    for i, (_, directions) in enumerate(rows):
        page.insert_text((315, 130 + 22 * i), directions, fontsize=10)
    page.insert_text((50, 250), 'Allergies', fontsize=11)
    page.insert_text((50, 275), 'Unconfirmed synthetic entry', fontsize=9)
    page.insert_text((50, 300), 'Synthetic GP details, test date and fictional source context only.', fontsize=9)
    doc.save(pdf)
    doc.close()
    import referral
    raw = interview.referral_text(folder)[0]
    text_path = referral.parse(raw)
    assert len(text_path['unattributed_directions']) == 3  # PDF stream order differs from the table.
    geometry = interview.geometry_table(folder)
    assert geometry['ok'], geometry
    assert geometry['rows'] == [list(row) for row in rows]

    reviewed = {'confirmed': True, 'source_page': 1, 'reviewed_by': 'Synthetic Pharmacist',
                'allergies_status': 'unknown', 'conditions': '', 'allergies': '', 'observations': '',
                'medicines': '\n'.join(name + ' - ' + directions for name, directions in rows)}
    (folder / 'referral_source.json').write_text(json.dumps({'clinical_review': reviewed}))
    conn = db.connect(str(tmp_path / 'userdata' / 'hmr.db'))
    try:
        with conn:
            pid = conn.execute("INSERT INTO patients(key,name,folder) VALUES (?,?,?)",
                               ('synthetic','Synthetic Patient','TO SORT/Synthetic')).lastrowid
        patient = conn.execute('SELECT * FROM patients WHERE id=?', (pid,)).fetchone()
        record = interview.blank(conn, patient)
        assert [r[:2] for r in record['meds']] == [list(r) for r in rows]
        assert all(r[2:] == ['', '', ''] for r in record['meds'])
        assert any('unusual word' in x and 'Taplet' in x for x in record['clarify'])
        assert all(not m.get('use_status') and not m.get('checked') for m in record['details']['meds'])
        interview.validate(record)
    finally:
        conn.close()
