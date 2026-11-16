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
    assert confirmed['meds'] == []  # No invented medicine rows or actual-use directions.
    interview.validate(confirmed)
    conn.close()
