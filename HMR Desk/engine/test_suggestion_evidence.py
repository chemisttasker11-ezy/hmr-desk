"""Synthetic production evidence linkage and unsupported-trigger regressions."""
import copy
import datetime as dt
import hashlib
import json

import pytest
import api
import db
import interview
import medicine_snapshot as ms
import pathology_records
import records
import suggest
import suggestion_context as sc
from test_medicine_snapshot import setup

TODAY=dt.date(2026,11,17)

def save(setup):
    conn,p,data=setup
    data['revision']='missing'
    data['notes']='Denies falls. Previous renal issue, current status unknown.'
    data['obs']=[['BP','80/50','120/80'],['Pulse','','70']]
    data['pathology']=[['eGFR','41','2026-11-01','legacy only']]
    return conn,p,interview.save(conn,p,data)

def pathology(conn,p,**updates):
    row=dict(id='c'*32,test='eGFR',value='41',unit='mL/min/1.73m2',reference_interval='original range',
             sample_date='2026-11-01',source='synthetic-lab.pdf page 2',verified=True,comment='Original comment')
    row.update(updates)
    return pathology_records.save(conn,p,{'revision':pathology_records.revision(conn,p),'records':[row]},reviewer='Synthetic Reviewer')

def index():
    cases=[{'age':80,'meds':[{'row':['Synthetic'], 'kind':'current'}],
            'Obs from interview':'falls renal blood pressure', 'pathology':[],
            'findings':[{'title':'Synthetic falls renal blood pressure review','rec':'Review original evidence before choosing an action','rationale':'Synthetic template, not patient facts'}]} for _ in range(8)]
    return suggest.make_index(cases,'','',mapping={'synthetic':['synthetic class']})

def test_original_versions_dates_units_and_verified_pathology_are_separate(setup):
    conn,p,_=save(setup);pathology(conn,p)
    before=records.get(conn,p['id'],'interview.json');changes=conn.total_changes
    c=sc.build(conn,p,TODAY);byid={e['id']:e for e in c['evidence']}
    assert byid['obs:0:referral']['text']=='BP: 80/50' and not byid['obs:0:referral']['eligible']
    assert byid['obs:0:interview']['text']=='BP: 120/80' and byid['obs:0:interview']['eligible']
    assert 'Date not established' in byid['obs:0:interview']['flags']
    lab=byid['pathology:'+'c'*32]
    assert lab['unit']=='mL/min/1.73m2' and lab['date']=='2026-11-01' and lab['age_days']==16
    assert lab['source']=='synthetic-lab.pdf page 2' and lab['reference_interval']=='original range'
    assert lab['verification']=='named pharmacist verified'
    assert not byid['legacy_pathology:0']['eligible']
    assert conn.total_changes==changes and records.get(conn,p['id'],'interview.json')==before
    assert suggest.context_for(conn,p)['evidence_version']==1

def test_no_numeric_age_or_negation_as_fact_triggers_in_production(setup):
    conn,p,_=save(setup);c=sc.build(conn,p,TODAY)
    c.update(age=90,obs='BP 80/50 Denies falls',labs=['eGFR 12'])
    assert suggest.context_rules(c)=={}
    # Legacy evaluator behavior is recorded, not approved for clinical use.
    assert 'topic:hypotension' in suggest.context_rules({'obs':'BP 80/50','labs':[]})
    hits=suggest.suggest(c,index());assert hits
    assert all('falls noted' not in ' '.join(h['why']) for h in hits)
    assert all('not a probability or guideline' in ' '.join(h['why']) for h in hits)
    assert any(any('Denies falls' in e['text'] for e in h['evidence']) for h in hits)
    assert all(h['context_snapshot_sha256']==c['context_snapshot_sha256'] for h in hits)

def test_unverified_missing_future_pathology_is_explicit_and_future_not_ranked(setup):
    conn,p,_=save(setup);pathology(conn,p,sample_date='2026-11-18',unit='',source='',reference_interval='',verified=False)
    c=sc.build(conn,p,TODAY);e=next(e for e in c['evidence'] if e['kind']=='pathology')
    assert not e['eligible'] and e['age_days']==-1
    assert {'Future date: check original','Units missing','Source missing','Reference interval not recorded'} <= set(e['flags'])
    assert e['verification'].startswith('UNVERIFIED') and 'No clinical expiry inferred' in ' '.join(c['context_gaps'])
    assert not any(e['id']==x['id'] for h in suggest.suggest(c,index()) for x in h['evidence'])

def test_snapshot_changes_for_note_pathology_and_medicine_identity_edits(setup):
    conn,p,saved=save(setup);one=sc.build(conn,p,TODAY)
    assert sc.build(conn,p,TODAY)['context_snapshot_sha256']==one['context_snapshot_sha256']
    saved['notes']+=' Additional synthetic observation';saved=interview.save(conn,p,saved)
    two=sc.build(conn,p,TODAY);assert one['context_snapshot_sha256']!=two['context_snapshot_sha256']
    pathology(conn,p);three=sc.build(conn,p,TODAY);assert two['context_snapshot_sha256']!=three['context_snapshot_sha256']
    saved['details']['meds'][0]['reference']['code']='1002';interview.save(conn,p,saved)
    assert sc.build(conn,p,TODAY)['context_snapshot_sha256']!=three['context_snapshot_sha256']

def test_stale_confirmation_never_substitutes_old_medicines_or_ceased_rows(setup):
    conn,p,saved=save(setup)
    records.put_json(conn,p['id'],'confirmed_meds.json',{'meds':[['Old synthetic','']], 'allergies':[],
        'medicine_snapshot_sha256':ms.digest(ms.snapshot(saved))});conn.commit()
    saved['details']['meds'][0]['use_status']='not_using';saved=interview.save(conn,p,saved)
    c=sc.build(conn,p,TODAY)
    assert not c['medicine_confirmation_current'] and 'Old synthetic' not in c['meds'] and saved['meds'][0][0] not in c['meds']
    assert 'stale' in ' '.join(c['context_gaps'])

def test_api_context_endpoint_read_only_and_bound_exact_result_only(setup,monkeypatch):
    conn,p,saved=save(setup)
    conf={'meds':[['Synthetic','']], 'allergies':[],'medicine_snapshot_sha256':ms.digest(ms.snapshot(saved))}
    records.put_json(conn,p['id'],'confirmed_meds.json',conf);conn.commit()
    confirmed=records.get(conn,p['id'],'confirmed_meds.json');text=b'Synthetic portal wording. No inference.'
    name='MIMS interactions generated '+hashlib.sha256(confirmed).hexdigest()+' '+hashlib.sha256(text).hexdigest()+'.txt'
    records.put(conn,p['id'],name,text);records.put(conn,p['id'],'MIMS interactions old.txt',b'Old unmatched result');conn.commit()
    c=sc.build(conn,p,TODAY);assert c['interactions']==text.decode() and 'Old unmatched' not in c['interactions']
    monkeypatch.setattr(suggest,'build_index',index)
    changes=conn.total_changes
    status,out=api.handle(conn,'GET',f"/api/patients/{p['id']}/suggestions",{},None)
    status2,fresh=api.handle(conn,'GET',f"/api/patients/{p['id']}/suggestions/context",{},None)
    assert status==status2==200 and fresh['context_snapshot_sha256']==out['context_snapshot_sha256']
    assert conn.total_changes==changes


def test_selected_evidence_roundtrip_report_and_exact_backup(setup):
    import report
    conn,p,saved=save(setup)
    records.put_json(conn,p['id'],'confirmed_meds.json',{'meds':[['Synthetic','']], 'allergies':[],
        'medicine_snapshot_sha256':ms.digest(ms.snapshot(saved))});conn.commit()
    c=sc.build(conn,p,TODAY);hit=suggest.suggest(c,index())[0]
    spec=report.start(conn,p)
    origin={'version':1,'context_snapshot_sha256':c['context_snapshot_sha256'],'evidence':hit['evidence']}
    spec['issues']=[{'title':hit['title'],'rec':hit['rec'],'rationale':hit['rationale'],'suggestion_source':origin}]
    report.save(conn,p,spec);original=records.get(conn,p['id'],'report_spec.json')
    spec['issues'][0]['rec']='Pharmacist edited synthetic wording';report.save(conn,p,spec)
    assert records.get(conn,p['id'],'report_spec.json.bak')==original
    assert report.load(conn,p)['issues'][0]['suggestion_source']==origin
    assert b'context_snapshot_sha256' in records.get(conn,p['id'],'report_spec.json')
    bad=copy.deepcopy(spec);bad['issues'][0]['suggestion_source']['context_snapshot_sha256']='not a digest'
    with pytest.raises(ValueError,match='source evidence'): report.validate(bad)


def test_legacy_verified_flag_without_named_audit_is_not_promoted(setup):
    conn,p,_=save(setup);pathology(conn,p)
    data=records.get_json(conn,p['id'],'pathology_records.json')
    data['verification']['c'*32]={}
    records.put_json(conn,p['id'],'pathology_records.json',data);conn.commit()
    c=sc.build(conn,p,TODAY)
    e=next(e for e in c['evidence'] if e['kind']=='pathology')
    assert e['verification'].startswith('UNVERIFIED') and not e['verified_by']
