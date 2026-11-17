"""Synthetic shared-item compatibility; no licensed data or portal queries."""
import copy
import json
from pathlib import Path

import pytest
import api
import db
import interview
import jobs
import medicine_snapshot as ms
import records


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'BASE', str(tmp_path/'workspace'))
    monkeypatch.setattr(db, 'DATA_DIR', str(tmp_path/'userdata'))
    folder=tmp_path/'workspace'/'Visited'/'Synthetic';folder.mkdir(parents=True)
    conn=db.connect(str(tmp_path/'userdata'/'hmr.db'))
    pid=conn.execute("INSERT INTO patients(key,name,state,folder) VALUES(?,?,?,?)",('synthetic-items','Synthetic Items','visited','Visited/Synthetic')).lastrowid
    conn.commit();patient=conn.execute('SELECT * FROM patients WHERE id=?',(pid,)).fetchone()
    data=interview.blank(conn,patient)
    data['meds']=[['Synthetic 5 mg MR','one daily','one daily','',''],['Free text','','','','']]
    data['other_meds']=[['Synthetic supplement','PRN','','']]
    data['details']['meds']=[{'packed':'','as_instructed':False,'use_status':'taking','use_reason':'','use_details':'','reference':{'source':'amt','code':'1001','display':'Synthetic 5 mg MR','release':'20260101'}},{'packed':'','as_instructed':False}]
    data['details']['other_meds']=[{'checked':False,'priority':0}]
    interview.validate(data)
    yield conn,patient,data
    conn.close()


def test_reads_never_assign_or_rewrite_and_explicit_save_retains_original_bytes(setup):
    conn,p,data=setup
    raw=records.dumps(data)
    records.put(conn,p['id'],'interview.json',raw);conn.commit()
    loaded=interview.load(conn,p)
    snap=ms.snapshot(loaded)
    assert all(item['item_id'] is None for item in snap['items'])
    assert records.get(conn,p['id'],'interview.json')==raw
    saved=interview.save(conn,p,loaded)
    ids=[item['item_id'] for item in ms.snapshot(saved)['items']]
    assert len(set(ids))==3 and all(ms.valid_id(i) for i in ids)
    assert records.get(conn,p['id'],'interview.json.bak')==raw
    again=interview.load(conn,p)
    assert [item['item_id'] for item in ms.snapshot(again)['items']]==ids
    assert again['meds']==data['meds'] and again['details']['meds'][0]['reference']==data['details']['meds'][0]['reference']
    assert not again['details']['meds'][1].get('use_status')
    assert 'reviewed_by' not in json.dumps(again)


def test_save_reorder_delete_and_conflict_preserve_row_ids(setup):
    conn,p,data=setup
    data['revision']='missing';saved=interview.save(conn,p,data)
    ids=[item['item_id'] for item in ms.snapshot(saved)['items']]
    stale=copy.deepcopy(saved)
    for key in ('meds',):
        saved[key].reverse();saved['details'][key].reverse()
    saved=interview.save(conn,p,saved)
    assert [item['item_id'] for item in ms.snapshot(saved)['items']]==[ids[1],ids[0],ids[2]]
    saved['meds'].pop(0);saved['details']['meds'].pop(0)
    saved=interview.save(conn,p,saved)
    assert [item['item_id'] for item in ms.snapshot(saved)['items']]==[ids[0],ids[2]]
    before=records.get(conn,p['id'],'interview.json')
    with pytest.raises(interview.Conflict):interview.save(conn,p,stale)
    assert records.get(conn,p['id'],'interview.json')==before


def test_failure_after_write_rolls_back_bytes_and_backup(setup,monkeypatch):
    conn,p,data=setup
    data['revision']='missing';saved=interview.save(conn,p,data)
    before=records.get(conn,p['id'],'interview.json');backup=records.get(conn,p['id'],'interview.json.bak')
    saved['meds'][0][0]='Synthetic edited'
    def fail(*a,**kw):raise RuntimeError('synthetic rollback checkpoint')
    monkeypatch.setattr(db,'log',fail)
    with pytest.raises(RuntimeError):interview.save(conn,p,saved)
    assert records.get(conn,p['id'],'interview.json')==before
    assert records.get(conn,p['id'],'interview.json.bak')==backup


def test_duplicate_and_invalid_ids_reject(setup):
    _,_,data=setup
    saved=ms.assign_ids(data)
    saved['details']['other_meds'][0]['item_id']=saved['details']['meds'][0]['item_id']
    with pytest.raises(ValueError):interview.validate(saved)
    for bad in ('','a'*31,'X'*32,5,None):
        changed=copy.deepcopy(data);changed['details']['meds'][0]['item_id']=bad
        with pytest.raises(ValueError):interview.validate(changed)


@pytest.mark.parametrize('mutation',['code','release','use','directions','name','allergies'])
def test_full_medicine_snapshot_changes(mutation,setup):
    _,_,data=setup
    data=ms.assign_ids(data);original=ms.digest(ms.snapshot(data))
    if mutation in ('code','release'):data['details']['meds'][0]['reference'][mutation]+='9'
    elif mutation=='use':data['details']['meds'][0]['use_status']='not_using'
    elif mutation=='directions':data['meds'][0][2]='half daily'
    elif mutation=='name':data['meds'][0][0]='Synthetic other'
    else:data['allergies']='Synthetic allergy'
    assert ms.digest(ms.snapshot(data))!=original


def test_legacy_absent_details_read_and_explicit_save(setup):
    conn,p,data=setup
    data.pop('details');data['revision']='missing'
    interview.validate(data)
    assert all(item['metadata'] is None for item in ms.snapshot(data)['items'])
    saved=interview.save(conn,p,data)
    assert saved['meds']==data['meds'] and all(item['item_id'] for item in ms.snapshot(saved)['items'])


def test_saved_interview_wins_over_stale_or_corrupt_spec(setup):
    conn,p,data=setup
    records.put_json(conn,p['id'],'interview.json',data)
    records.put_json(conn,p['id'],'interview_spec.json',{'meds':[['Synthetic old medicine','daily','']]})
    path=jobs.interview_spec_path(p);path.parent.mkdir(parents=True,exist_ok=True);path.write_text('not valid json')
    assert api.proposal(conn,p)['meds']==[['Synthetic 5 mg MR',''],['Synthetic supplement','']]


def test_confirm_snapshot_required_and_identity_only_change_invalidates(setup):
    conn,p,data=setup
    data['revision']='missing';saved=interview.save(conn,p,data)
    path=f"/api/patients/{p['id']}/meds"
    status,proposal=api.handle(conn,'GET',path,{},None)
    assert status==200
    body={k:proposal[k] for k in ('meds','allergies','interview_usage','medicine_snapshot_sha256')}
    assert api.handle(conn,'POST',path,{},body)[0]==200
    assert api.confirmed_medicines_current(conn,p)
    confirmed=records.get_json(conn,p['id'],'confirmed_meds.json')
    assert confirmed['medicine_snapshot']['items'][0]['metadata']['reference']['code']=='1001'
    assert confirmed['medicine_snapshot']['items'][0]['item_id']==saved['details']['meds'][0]['item_id']
    saved['details']['meds'][0]['reference']['code']='1002'
    interview.save(conn,p,saved)
    assert not api.confirmed_medicines_current(conn,p)
    _,updated=api.handle(conn,'GET',path,{},None)
    assert updated['medicine_snapshot_changed'] and updated['medicine_snapshot']['items'][0]['metadata']['reference']['code']=='1002'
    assert api.handle(conn,'POST',path,{},body)[0]==400
    body.pop('medicine_snapshot_sha256')
    assert api.handle(conn,'POST',path,{},body)[0]==400


def test_canonical_snapshot_keeps_persisted_identity_without_changing_legacy(setup):
    import clinical_snapshot
    _,_,data=setup
    legacy=clinical_snapshot._medicine_rows(data,'meds')
    assert 'item_id' not in legacy[0] and 'reference' not in legacy[0]
    saved=ms.assign_ids(data)
    rows=clinical_snapshot._medicine_rows(saved,'meds')
    assert rows[0]['item_id']==saved['details']['meds'][0]['item_id']
    assert rows[0]['reference']['code']=='1001'
    rows[0]['reference']['code']='changed'
    assert saved['details']['meds'][0]['reference']['code']=='1001'


def test_stored_record_and_snapshot_roundtrip_through_labelled_record_export(setup,tmp_path):
    conn,p,data=setup
    data['revision']='missing';saved=interview.save(conn,p,data)
    # Provider-independent record serialization is also the backup payload boundary.
    encoded=records.dumps(saved)
    decoded=json.loads(encoded)
    interview.validate(decoded)
    assert ms.snapshot(decoded)==ms.snapshot(saved)
    assert interview.medicine_rows(decoded)[0][0]==data['meds'][0][0]


def test_real_backup_restore_preserves_ids_reference_and_exact_record_bytes(setup,tmp_path):
    import backup_bundle
    import sqlite3
    conn,p,data=setup
    data['revision']='missing';saved=interview.save(conn,p,data)
    raw=records.get(conn,p['id'],'interview.json')
    bundle=tmp_path/'synthetic.hmrbak';restore=tmp_path/'isolated-recovery'
    phrase='synthetic-test-backup-passphrase-only'
    backup_bundle.create(conn,Path(db.BASE),bundle,phrase)
    backup_bundle.restore(bundle,restore,phrase)
    assert backup_bundle.verify_isolated(restore)['verified']
    with sqlite3.connect(restore/'data'/'hmr.db') as recovered:
        recovered.row_factory=sqlite3.Row
        restored=records.get(recovered,p['id'],'interview.json')
        assert restored==raw
        assert ms.snapshot(json.loads(restored))==ms.snapshot(saved)
    exported=tmp_path/'labelled-export'
    records.export_folder(conn,p['id'],exported)
    assert (exported/'interview.json').read_bytes()==raw
    assert 'OUTSIDE the encryption' in (exported/records.EXPORT_NOTE).read_text()


def test_report_source_snapshot_survives_native_docx_template_adapter(setup,tmp_path):
    import report
    import template_report_builder
    from test_template_report_builder import make_template
    from docx import Document
    conn,p,data=setup
    data['revision']='missing';saved=interview.save(conn,p,data)
    path=f"/api/patients/{p['id']}/meds"
    _,proposal=api.handle(conn,'GET',path,{},None)
    body={k:proposal[k] for k in ('meds','allergies','interview_usage','medicine_snapshot_sha256')}
    assert api.handle(conn,'POST',path,{},body)[0]==200
    spec=report.start(conn,p)
    assert spec['medicine_snapshot']['items'][0]['item_id']==saved['details']['meds'][0]['item_id']
    assert spec['medicine_snapshot']['items'][0]['metadata']['reference']['code']=='1001'
    spec['issues']=[{'title':'Synthetic review','rec':'Synthetic pharmacist recommendation','rationale':'Synthetic rationale'}]
    template=tmp_path/'synthetic.docx';output=tmp_path/'synthetic-report.docx'
    make_template(template)
    template_report_builder.render(spec,output,template)
    doc=Document(output)
    assert any('Synthetic 5 mg MR' in cell.text for table in doc.tables for row in table.rows for cell in row.cells)
    assert report.load(conn,p)['medicine_snapshot']==spec['medicine_snapshot']

@pytest.mark.parametrize('change', ['use', 'identity', 'directions', 'allergies'])
def test_stale_confirmation_blocks_readiness_done_and_next_action(setup, monkeypatch, tmp_path, change):
    import steps
    conn, p, data = setup
    data['revision'] = 'missing'
    saved = interview.save(conn, p, data)
    path = f"/api/patients/{p['id']}/meds"
    _, proposal = api.handle(conn, 'GET', path, {}, None)
    body = {k: proposal[k] for k in ('meds', 'allergies', 'interview_usage', 'medicine_snapshot_sha256')}
    assert api.handle(conn, 'POST', path, {}, body)[0] == 200
    assert steps.done('confirm_medicines', conn, p)
    assert steps.ready('interactions', conn, p)[0]
    if change == 'use': saved['details']['meds'][0]['use_status'] = 'not_using'
    elif change == 'identity': saved['details']['meds'][0]['reference']['code'] = '1002'
    elif change == 'directions': saved['meds'][0][2] = 'synthetic changed directions'
    else: saved['allergies'] = 'synthetic changed allergy'
    interview.save(conn, p, saved)
    assert not steps.done('confirm_medicines', conn, p)
    for name in ('interactions', 'report_start'):
        assert steps.ready(name, conn, p) == (False, 'confirm the medicine list first')
    assert api._next_step(p, conn) == 'confirm medicines'
    # Real production path with an application-owned synthetic helper file present.
    # No script executes: mims_lists only checks availability before validating snapshots.
    helper = tmp_path/'make-lists.py'; helper.write_text('# synthetic availability only')
    monkeypatch.setattr(api, 'MIMS_PATH', helper)
    with pytest.raises(ValueError, match='Medicine use changed or needs reconciliation'):
        api.mims_lists(conn)
