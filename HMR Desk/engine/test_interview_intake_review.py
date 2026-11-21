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

    All details are synthetic. This documents only the explicit-hyphen exact-match case.
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
        # A reviewer list differing in even one letter has no exact verified
        # pairing. Keep the full reviewer lines and show the old parsed text
        # rather than silently deciding which source is correct.
        reviewed['medicines'] = reviewed['medicines'].replace('1 Taplet Daily', '1 Tablet Daily')
        (folder / 'referral_source.json').write_text(json.dumps({'clinical_review': reviewed}))
        uncertain = interview.blank(conn, patient)
        assert uncertain['meds'][0][:2] == ['Lunovex 5mg Tablet - 1 Tablet Daily', '']
        assert any('Parser read:' in x and 'Taplet' in x for x in uncertain['clarify'])
        assert all(not meta.get('use_status') for meta in uncertain['details']['meds'])
    finally:
        conn.close()



def _four_medicine_referral_pdf(path, *, ambiguous=False, image_layer=False):
    """Generate an invented 4-row referral; no real clinical material enters the test."""
    import fitz
    rows = [
        ('Lunovex 5mg Tablet', '1 Taplet Daily'),
        ('Fictamol 10mg Capsule', '2 Capsules At night'),
        ('Nuvrala 20mg Tablet', '1 Tablet With meals'),
        ('Virelune 15mg Drops', '3 Drops Each morning'),
    ]
    doc = fitz.open()
    page = doc.new_page()
    if image_layer:
        # A generated full-page image underneath live PDF text represents the
        # risk shape of an image with a potentially conflicting text layer.
        # It does not test OCR accuracy or prove that the image and layer differ.
        bitmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 612, 792), False)
        bitmap.clear_with(255)
        page.insert_image(page.rect, stream=bitmap.tobytes('png'))
    page.insert_text((50, 45), 'Home Medicines Review referral', fontsize=11)
    page.insert_text((50, 65), 'Patient Details', fontsize=11)
    page.insert_text((50, 85), 'Name: Mr Synthetic Example', fontsize=10)
    page.insert_text((50, 96), 'Medical History', fontsize=10)
    page.insert_text((50, 105), 'Current Medications', fontsize=11)
    if ambiguous:
        # One column, names-first. The text path must not guess which of
        # these four unpaired directions belongs to which medicine.
        for i, (name, _) in enumerate(rows):
            page.insert_text((50, 135 + 22 * i), name, fontsize=10)
        for i, (_, direction) in enumerate(rows):
            page.insert_text((50, 235 + 22 * i), direction, fontsize=10)
        allergy_y = 355
    else:
        # The PDF content stream stores *all names* then *all directions*.
        # Visual two-column row positions, not stream order, support pairing.
        for i, (name, _) in enumerate(rows):
            page.insert_text((50, 135 + 22 * i), name, fontsize=10)
        for i, (_, direction) in enumerate(rows):
            page.insert_text((315, 135 + 22 * i), direction, fontsize=10)
        allergy_y = 260
    page.insert_text((50, allergy_y), 'Allergies', fontsize=11)
    page.insert_text((50, allergy_y + 25), 'Synthetic source information requires independent review.', fontsize=10)
    doc.save(path)
    doc.close()
    return rows


@pytest.mark.parametrize('scenario', ['unchanged', 'changed', 'ambiguous', 'image_layer'])
def test_real_intake_four_medicine_source_to_saved_interview(tmp_path, monkeypatch, scenario):
    """Use actual referral_entry.review/commit and interview.load/save with an original synthetic PDF.

    Intake text is separate from the PDF parser output. No punctuation delimiter is assumed.
    """
    import fitz
    import records

    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    monkeypatch.setattr(db, 'BASE', str(workspace))
    monkeypatch.setattr(db, 'DATA_DIR', str(tmp_path / 'userdata'))
    original = tmp_path / 'synthetic-original-referral.pdf'
    rows = _four_medicine_referral_pdf(
        original, ambiguous=scenario == 'ambiguous', image_layer=scenario == 'image_layer'
    )
    with fitz.open(original) as document:
        stream = document[0].get_text()
        assert stream.index(rows[-1][0]) < stream.index(rows[0][1])
    original_bytes = original.read_bytes()
    conn = db.connect(str(tmp_path / 'userdata' / 'hmr.db'))
    try:
        # This is the real application intake reader and field validation, NOT
        # a replacement parser or a seeded interview JSON document.
        item = referral_entry.review(conn, [str(original)])['rows'][0]
        assert item['status'] == 'review', item
        assert item['page_previews'][0]['method'] == 'text'
        assert 'Taplet' in item['page_previews'][0]['text']
        assert item['sha256']
        confirmation_lines = [name + ' ' + direction for name, direction in rows]
        if scenario == 'changed':
            confirmation_lines[0] = confirmation_lines[0].replace('Taplet', 'Tablet')
        clinical = {
            'confirmed': True, 'reviewed_by': 'Synthetic Pharmacist',
            'allergies_status': 'unknown',
            'source_pages': {'medicines': 1, 'conditions': 0, 'allergies': 0, 'observations': 0},
            'medicines': '\n'.join(confirmation_lines),
            'conditions': '', 'allergies': '', 'observations': '',
        }
        # The real intake UI submits only the documented identity-field keys.
        fields = {key: value for key, value in item['fields'].items()
                  if key in referral_entry.FIELDS}
        fields['name'] = 'Synthetic Example'
        pid = referral_entry.commit(
            conn, item['token'], fields,
            clinical=clinical
        )['patient_id']
        patient = conn.execute('SELECT * FROM patients WHERE id=?', (pid,)).fetchone()
        patient_folder = workspace / patient['folder']
        assert (patient_folder / 'referral.pdf').read_bytes() == original_bytes
        assert records.get(conn, pid, 'interview.json') is not None, 'Intake must persist the prepared interview'
        source_review = json.loads((patient_folder / 'referral_source.json').read_text(encoding='utf-8'))
        assert source_review['clinical_review']['medicines'] == '\n'.join(confirmation_lines)
        assert source_review['clinical_review']['source_pages']['medicines'] == 1
        assert 'Taplet' in source_review['page_excerpts_unconfirmed'][0]['text']

        from_source = interview.geometry_table(patient_folder)
        text, text_flags = interview.referral_text(patient_folder)
        import referral
        by_text = referral.parse(text)
        assert 'Taplet' in text and not text_flags
        if scenario == 'ambiguous':
            assert not from_source['ok']
            assert len(by_text['unattributed_directions']) == 4
        else:
            assert from_source['ok'], from_source
            assert from_source['rows'] == [list(r) for r in rows]
            assert len(by_text['unattributed_directions']) == 4

        data = interview.load(conn, patient)
        assert data['saved'] is True
        if scenario in ('unchanged', 'image_layer'):
            assert [r[:2] for r in data['meds']] == [list(r) for r in rows]
            assert all('location' in meta.get('source_evidence', {}) for meta in data['details']['meds'])
            assert any('unusual word' in message and 'Taplet' in message for message in data['clarify'])
        else:
            # Neither a changed character nor ambiguous one-column positions
            # grant permission to infer direction cells. Keep the pharmacist's
            # entire typed line; retain the source warning and old read.
            assert [r[:2] for r in data['meds']] == [[line, ''] for line in confirmation_lines]
            if scenario == 'changed':
                assert any('Parser read:' in note and 'Taplet' in note for note in data['clarify'])
            else:
                assert any('not read by page position' in note for note in data['clarify'])
                assert any('not matched to a medicine' in note for note in data['clarify'])
        if scenario == 'image_layer':
            assert any('images with a text layer' in note for note in data['clarify'])
            assert any('Taplet' in note and 'unusual word' in note for note in data['clarify'])
        assert len(data['details']['meds']) == 4
        assert all(not meta.get('use_status') and not meta.get('checked')
                   and 'reference' not in meta for meta in data['details']['meds'])

        # Save an actual pharmacist edit to both cells, then use the REAL
        # review/duplicate-commit path to prove it cannot reset a saved record.
        data['meds'][0][0] = 'Lunovex 5mg Tablet manually edited'
        data['meds'][0][1] = 'Fictional directions entered during interview'
        interview.save(conn, patient, data)
        conn.commit()
        before_duplicate = records.get(conn, pid, 'interview.json')
        duplicate = referral_entry.review(conn, [str(original)])['rows'][0]
        assert duplicate['status'] == 'duplicate'
        assert duplicate['duplicate_kind'] == 'content'
        with pytest.raises(ValueError, match='already added'):
            referral_entry.commit(
                conn, duplicate['token'], fields,
                clinical=clinical
            )
        reopened = interview.load(conn, patient)
        assert reopened['meds'][0][:2] == [
            'Lunovex 5mg Tablet manually edited',
            'Fictional directions entered during interview',
        ]
        assert records.get(conn, pid, 'interview.json') == before_duplicate
        assert all(not meta.get('use_status') for meta in reopened['details']['meds'])
        assert (patient_folder / 'referral.pdf').read_bytes() == original_bytes
    finally:
        conn.close()
