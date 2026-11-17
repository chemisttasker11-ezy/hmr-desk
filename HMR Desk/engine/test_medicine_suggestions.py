"""Synthetic terminology and referral proposals, never clinical identity confirmation."""
import contextlib
import hashlib
import json
from pathlib import Path

import pytest
import api
import db
import interview
import medicine_reference as ref
from medicine_data import catalog
import records


@pytest.fixture
def catalogue(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DATA_DIR',str(tmp_path/'userdata'))
    path=ref.reference_path();conn=catalog.connect(path)
    source=tmp_path/'synthetic-source.txt';source.write_text('SYNTHETIC ONLY')
    with catalog.snapshot(conn,'amt','20260101',source,'https://example.invalid/synthetic'):
        catalog.add_medicine(conn,'amt','1001','Syntheticmed 5 mg MR tablet','MPUU',generic='Syntheticmed 5 mg MR tablet',form='tablet')
        catalog.add_medicine(conn,'amt','1002','Syntheticmed 5 mg tablet','MPUU',generic='Syntheticmed 5 mg tablet',form='tablet')
        catalog.add_medicine(conn,'amt','1003','Syntheticbrand 5 mg MR tablet','TPUU',generic='Syntheticmed 5 mg MR tablet',brand='Syntheticbrand',form='tablet')
        catalog.add_medicine(conn,'amt','1004','Duplicate 10 mg tablet','MPUU')
        catalog.add_medicine(conn,'amt','1005','Duplicate 10 mg tablet','TPUU')
        for i in range(20):catalog.add_medicine(conn,'amt',str(2000+i),f'Broadcandidate {i} mg tablet','MPUU')
    conn.close()
    return path


def test_exact_is_proposed_only_and_formulation_not_lost(catalogue):
    before=catalogue.read_bytes();out=ref.suggest_many(['Syntheticmed 5 mg MR tablet','Syntheticmed 5 mg tablet','Syntheticbrand 5 mg MR tablet'])
    assert [r['state'] for r in out['results']]==['exact_candidate']*3
    assert [r['candidates'][0]['code'] for r in out['results']]==['1001','1002','1003']
    assert out['results'][2]['candidates'][0]['generic_name']=='Syntheticmed 5 mg MR tablet'
    assert catalogue.read_bytes()==before
    assert 'reference' not in out and all('selected' not in x and 'confirmed' not in x for x in out['results'])


def test_ambiguous_partial_strength_ocr_and_missing_remain_review(catalogue):
    queries=['Duplicate 10 mg tablet','Syntheticmed 5mg tablet','Syntheticmed Omg tablet','Syntheticmed 500 microgram tablet','Missingdrug 5 mg tablet']
    result=ref.suggest_many(queries)['results']
    assert result[0]['state']=='ambiguous' and len(result[0]['candidates'])==2
    assert result[1]['state']=='review_candidates'
    assert result[2]['state']=='unmatched' # Never turn letter O into a dose digit.
    assert result[3]['state']=='review_candidates' # Broad candidates are not dose equivalence.
    assert result[4]['state']=='unmatched'
    assert [x['input_text'] for x in result]==queries


def test_truncation_wildcards_and_duplicate_query_order(catalogue):
    out=ref.suggest_many(['Broadcandidate','%','_','Broadcandidate'])['results']
    assert out[0]['truncated'] and len(out[0]['candidates'])==15
    assert out[0]['state']=='review_candidates'
    assert not out[1]['candidates'] and not out[2]['candidates']
    assert out[0]==out[3]


def test_missing_corrupt_catalogue_and_request_bounds(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DATA_DIR',str(tmp_path))
    assert ref.suggest_many(['Synthetic'])['results'][0]['state']=='unavailable'
    ref.reference_path().write_bytes(b'not a database')
    assert not ref.suggest_many(['Synthetic'])['installed']
    for bad in ('query',[None],['x']*81,['x'*20001]):
        with pytest.raises(ValueError):ref.suggest_many(bad)


def test_referral_source_lines_pages_and_actual_use_separate(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'BASE',str(tmp_path/'workspace'));monkeypatch.setattr(db,'DATA_DIR',str(tmp_path/'userdata'))
    folder=tmp_path/'workspace'/'Visited'/'Synthetic';folder.mkdir(parents=True)
    text='Medical History\nSynthetic condition\nCurrent Medications\n• Syntheticmed 5 mg MR tablet take one tablet\fonce daily\n'
    monkeypatch.setattr(interview,'referral_text',lambda folder:(text,[]))
    with contextlib.closing(db.connect(str(tmp_path/'userdata'/'hmr.db'))) as conn:
        pid=conn.execute("INSERT INTO patients(key,name,state,folder) VALUES(?,?,?,?)",('synthetic-source','Synthetic Source','visited','Visited/Synthetic')).lastrowid
        conn.commit();patient=conn.execute('SELECT * FROM patients WHERE id=?',(pid,)).fetchone()
        data=interview.blank(conn,patient);interview.validate(data)
        evidence=data['details']['meds'][0]['source_evidence']
        assert evidence['lines']==['• Syntheticmed 5 mg MR tablet take one tablet','once daily']
        assert evidence['page_candidates']==[[1],[2]]
        assert evidence['text_sha256']==hashlib.sha256(text.encode()).hexdigest()
        assert 'reference' not in data['details']['meds'][0]
        assert not data['details']['meds'][0].get('use_status') and not data['meds'][0][2]
        data['meds'][0][0]='Pharmacist chosen product'
        data['details']['meds'][0]['reference']={'source':'amt','code':'1001','display':'Synthetic chosen','release':'20260101'}
        data['revision']='missing';saved=interview.save(conn,patient,data)
        assert saved['details']['meds'][0]['source_evidence']==evidence
        assert interview.load(conn,patient)['details']['meds'][0]['source_evidence']==evidence


def test_api_suggestions_are_read_only_and_bad_shape_rejects(catalogue,tmp_path):
    with contextlib.closing(db.connect(str(tmp_path/'userdata'/'hmr.db'))) as conn:
        before=conn.total_changes
        status,out=api.handle(conn,'POST','/api/medicines/suggest',{}, {'queries':['Syntheticmed 5 mg MR tablet']})
        assert status==200 and out['results'][0]['state']=='exact_candidate'
        assert conn.total_changes==before
        assert api.handle(conn,'POST','/api/medicines/suggest',{}, {'queries':[], 'choose':True})[0]==400
