"""Synthetic evidence-to-reference retrieval; no clinical rules or patient data."""
import copy,json,datetime
import fitz,pytest
import api,db,interview,reference_library as library,reference_matches as matches,records,suggestion_context as sc
from test_medicine_snapshot import setup
from test_suggestion_evidence import pathology,save


def reference(tmp_path,monkeypatch):
    path=tmp_path/'synthetic-brainstorm.pdf';doc=fitz.open();p=doc.new_page()
    p.insert_text((72,60),'Brainstorm synthetic test catalogue',fontname='hebo',fontsize=16)
    p.insert_text((72,90),'Synthetic catalogue fixture only. No real reference or clinical recommendation is included.')
    p.insert_text((72,130),'Synthetic hydration',fontname='hebo',fontsize=16)
    p.insert_text((72,160),'First physical page context only; the matching wording continues on page two.')
    p=doc.new_page();p.insert_text((72,90),'Synthetic hydration source passage marker-alpha. Testing original physical page quote binding.')
    p=doc.new_page();p.insert_text((72,60),'eGFR',fontname='hebo',fontsize=16)
    p.insert_text((72,90),'eGFR synthetic source label only, not a threshold, diagnosis, recommendation or clinical rule.')
    p.insert_text((72,150),'Synthetic hydration',fontname='hebo',fontsize=16)
    p.insert_text((72,180),'Synthetic hydration marker-beta, a different original section with repeated heading.')
    doc.save(path);doc.close()
    library.register({'path':str(path),'edition':'Synthetic edition V1','local_use_confirmed':True});return path


def context(evidence):
    value={'evidence_version':1,'evidence':evidence,'checked_on':'2026-11-17','context_gaps':['No clinical expiry inferred'],
        'source_revisions':{'interview':'synthetic-revision','pathology':'synthetic-pathology-revision'}}
    value['context_snapshot_sha256']=sc.fingerprint(value);return value


def evidence(eid,kind,text,**extra):
    return {'id':eid,'kind':kind,'text':text,'eligible':True,'flags':['Date not established'],'date':'','source':'synthetic.json/'+eid,
        'verification':'recorded text, not diagnosis inference',**extra}


def test_automatic_matching_preserves_negation_history_and_page_context(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DATA_DIR',str(tmp_path/'data'));reference(tmp_path,monkeypatch)
    original=evidence('notes','interview notes','Denies synthetic hydration issue. Historical wording, uncertain relevance.')
    result=matches.retrieve(context([original]))
    assert result['total_matches']==2 and not result['truncated']
    assert [h['reference']['page'] for h in result['matches']]==[2,3]
    for hit in result['matches']:
        assert hit['evidence']==original
        assert hit['matched_heading_words']==['synthetic hydration']
        assert hit['review_status']=='pharmacist_review_required'
        assert 'not a clinical finding' in hit['limitations'][0]
        assert not any(k in hit for k in ['rec','recommendation','risk','case_count','probability'])
    assert result['matches'][0]['reference']['section_page']==1
    assert result['matches'][0]['reference']['section_page_end']==2


def test_observation_and_verified_pathology_keep_values_dates_units(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DATA_DIR',str(tmp_path/'data'));reference(tmp_path,monkeypatch)
    obs=evidence('obs:0:interview','observation','Synthetic hydration: original value unchanged')
    lab=evidence('pathology:'+'c'*32,'pathology','eGFR: synthetic value',verification='named pharmacist verified',verified_by='Synthetic Reviewer',verified_at='2026-11-17T12:00:00',unit='original units',date='2026-11-01',reference_interval='original interval',flags=[])
    result=matches.retrieve(context([obs,lab]))
    found=next(h for h in result['matches'] if h['evidence']['kind']=='pathology')
    assert found['evidence']==lab and found['reference']['page']==3
    assert found['evidence']['unit']=='original units' and found['evidence']['reference_interval']=='original interval'
    assert any(h['evidence']==obs for h in result['matches'])


def test_excluded_versions_future_unverified_legacy_do_not_drive_matches(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DATA_DIR',str(tmp_path/'data'));reference(tmp_path,monkeypatch)
    rows=[evidence('old','observation','Synthetic hydration',eligible=False),
        evidence('future','pathology','eGFR: synthetic',eligible=False),
        evidence('unverified','pathology','eGFR: synthetic',verification='UNVERIFIED: check original'),
        evidence('legacy','legacy pathology','eGFR: synthetic'),
        evidence('interactions','eMIMS result','Synthetic hydration')]
    result=matches.retrieve(context(rows));assert result['matches']==[]
    assert result['excluded_evidence_ids']==[e['id'] for e in rows]


def test_no_cross_word_synonym_or_threshold_inference(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DATA_DIR',str(tmp_path/'data'));reference(tmp_path,monkeypatch)
    rows=[evidence('notes','interview notes','synthetics hydrationless; kidney issue; result 15; synthetic unrelated hydration')]
    assert matches.retrieve(context(rows))['matches']==[]


def test_stale_context_and_changed_original_fail_closed(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DATA_DIR',str(tmp_path/'data'));path=reference(tmp_path,monkeypatch)
    ctx=context([evidence('notes','interview notes','Synthetic hydration')]);changed=copy.deepcopy(ctx);changed['evidence'][0]['text']='different'
    with pytest.raises(ValueError,match='fingerprint'):matches.retrieve(changed)
    path.write_bytes(path.read_bytes()+b'\nmodified')
    with pytest.raises(library.ReferenceUnavailable):matches.retrieve(ctx)


def test_explicit_truncation_never_claims_complete_review(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DATA_DIR',str(tmp_path/'data'));reference(tmp_path,monkeypatch)
    result=matches.retrieve(context([evidence(str(n),'interview notes','Synthetic hydration') for n in range(205)]))
    assert result['processed_evidence_rows']==200 and result['eligible_evidence_rows']==205
    assert result['truncated'] and len(result['matches'])==20 and result['total_matches']==400


def test_production_route_uses_saved_current_evidence_no_case_corpus(setup,tmp_path,monkeypatch):
    conn,p,data=setup;reference(tmp_path,monkeypatch)
    data['revision']='missing';data['notes']='Denies synthetic hydration issue, historical source text.'
    data['obs']=[['Synthetic hydration','old referral value','new interview value']]
    interview.save(conn,p,data)
    pathology(conn,p,test='eGFR')
    changes=conn.total_changes
    status,result=api.handle(conn,'GET',f"/api/patients/{p['id']}/reference-matches",{},None)
    assert status==200 and conn.total_changes==changes
    ids={h['evidence']['id'] for h in result['matches']}
    assert 'notes' in ids and 'obs:0:interview' in ids and 'obs:0:referral' not in ids
    assert 'pathology:'+'c'*32 in ids
    old=result['context_snapshot_sha256']
    saved=interview.load(conn,p);saved['notes']='No matching words';interview.save(conn,p,saved)
    status,new=api.handle(conn,'GET',f"/api/patients/{p['id']}/reference-matches",{},None)
    assert status==200 and new['context_snapshot_sha256']!=old
    assert not any(h['evidence']['id']=='notes' for h in new['matches'])
    assert api.handle(conn,'GET','/api/patients/99999/reference-matches',{},None)[0]==404
    library.registry_path().unlink()
    status,missing=api.handle(conn,'GET',f"/api/patients/{p['id']}/reference-matches",{},None)
    assert status==409 and missing['matches']==[] and missing['review_status']=='reference_unavailable'


def test_concurrent_saved_evidence_change_is_not_returned(setup,tmp_path,monkeypatch):
    conn,p,data=setup;reference(tmp_path,monkeypatch)
    original=sc.build(conn,p);changed=copy.deepcopy(original);changed['context_snapshot_sha256']='changed'
    contexts=iter((original,changed));monkeypatch.setattr(sc,'build',lambda *args:next(contexts))
    with pytest.raises(library.ReferenceUnavailable,match='changed during retrieval'):matches.for_patient(conn,p)


def test_heading_phrase_does_not_drop_negation_or_join_across_words():
    assert matches.matching_terms('Synthetic hydration','synthetic without hydration')==[]
    assert matches.matching_terms('Synthetic hydration','synthetic no hydration')==[]
    assert matches.matching_terms('Synthetic and hydration','synthetic and hydration')==[('synthetic','and','hydration')]
    assert matches.matching_terms('Synthetic and hydration','synthetic hydration')==[]


def test_quote_centres_real_matched_phrase_not_earlier_isolated_heading_word(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DATA_DIR',str(tmp_path/'data'));p=tmp_path/'long.pdf'
    doc=fitz.open();page=doc.new_page();page.insert_text((40,40),'Brainstorm fixture',fontname='hebo',fontsize=16)
    page.insert_text((40,70),'A long synthetic test-only catalogue with sufficient readable body text for registration.')
    page.insert_text((40,100),'Synthetic hydration',fontname='hebo',fontsize=16)
    page.insert_textbox(fitz.Rect(40,130,550,750),'synthetic unrelated start. '+('unrelated filler '*60)+' synthetic hydration true phrase marker.',fontsize=10)
    doc.save(p);doc.close();library.register({'path':str(p),'edition':'synthetic','local_use_confirmed':True})
    result=matches.retrieve(context([evidence('notes','interview notes','Synthetic hydration')]))
    assert len(result['matches'])==1
    assert 'synthetic hydration true phrase marker' in result['matches'][0]['reference']['snippet']


def test_registration_change_during_lookup_fails_closed(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DATA_DIR',str(tmp_path/'data'));reference(tmp_path,monkeypatch)
    original_current=library.current;old=original_current();new={**old,'edition':'changed user-reviewed edition'}
    states=iter((old,new));monkeypatch.setattr(library,'current',lambda:next(states))
    with pytest.raises(library.ReferenceUnavailable,match='Registered reference changed'):
        matches.retrieve(context([evidence('notes','interview notes','Synthetic hydration')]))


def test_heading_only_match_retrieves_opening_passage_without_false_body_match(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DATA_DIR',str(tmp_path/'data'));p=tmp_path/'heading.pdf'
    doc=fitz.open();page=doc.new_page();page.insert_text((40,40),'Brainstorm fixture',fontname='hebo',fontsize=16)
    page.insert_text((40,70),'A synthetic test-only catalogue with sufficient readable body text for registration.')
    page.insert_text((40,100),'Synthetic heading',fontname='hebo',fontsize=16)
    page.insert_text((40,130),'Opening section prose deliberately does not repeat any words from the title.')
    doc.save(p);doc.close();library.register({'path':str(p),'edition':'synthetic','local_use_confirmed':True})
    result=matches.retrieve(context([evidence('notes','interview notes','Denies synthetic heading; historic wording.')]))
    assert len(result['matches'])==1 and result['matches'][0]['quote_basis']=='heading_match_opening_passage'
    assert result['matches'][0]['reference']['snippet'].startswith('Opening section prose')
    assert result['storage']=='private_indexed_sqlite_tables'


def test_private_reference_index_tables_reuse_and_corrupt_rebuild(tmp_path,monkeypatch):
    import reference_tables,sqlite3
    monkeypatch.setattr(db,'DATA_DIR',str(tmp_path/'data'));reference(tmp_path,monkeypatch);source=library.current()
    conn=reference_tables.open_index(source,matches.anchors)
    assert conn.execute('SELECT edition FROM source').fetchone()[0]=='Synthetic edition V1'
    assert conn.execute('SELECT count(*) FROM sections').fetchone()[0]>=2
    assert conn.execute('SELECT count(*) FROM fragments').fetchone()[0]>=3
    assert any('anchors_first_word' in row[3] for row in conn.execute("EXPLAIN QUERY PLAN SELECT * FROM anchors WHERE first_word='synthetic'"))
    conn.close();original=__import__('brainstorm').sections
    monkeypatch.setattr(__import__('brainstorm'),'sections',lambda *args:(_ for _ in ()).throw(AssertionError('index should be reused')))
    conn=reference_tables.open_index(source,matches.anchors);conn.close()
    target=next((tmp_path/'data').glob('reference-index-v1-*.sqlite3'));target.write_bytes(b'corrupt')
    monkeypatch.setattr(__import__('brainstorm'),'sections',original)
    conn=reference_tables.open_index(source,matches.anchors);assert conn.execute('SELECT count(*) FROM anchors').fetchone()[0];conn.close()


def test_index_modified_anchor_cannot_fake_evidence_match(tmp_path,monkeypatch):
    import reference_tables
    monkeypatch.setattr(db,'DATA_DIR',str(tmp_path/'data'));reference(tmp_path,monkeypatch)
    conn=reference_tables.open_index(library.current(),matches.anchors)
    conn.execute('UPDATE anchors SET phrase=?,first_word=?,token_count=? WHERE rowid=(SELECT min(rowid) FROM anchors)',(json.dumps(['unrelated','words']),'unrelated',2));conn.commit();conn.close()
    with pytest.raises(library.ReferenceUnavailable,match='index does not match'):
        matches.retrieve(context([evidence('notes','interview notes','unrelated words')]))


def test_incomplete_anchor_table_rebuilds_instead_of_silent_no_matches(tmp_path,monkeypatch):
    import reference_tables
    monkeypatch.setattr(db,'DATA_DIR',str(tmp_path/'data'));reference(tmp_path,monkeypatch)
    conn=reference_tables.open_index(library.current(),matches.anchors);conn.execute('DELETE FROM anchors');conn.commit();conn.close()
    assert matches.retrieve(context([evidence('notes','interview notes','Synthetic hydration')]))['matches']


def test_unavailable_reference_tables_production_error_is_explicit(setup,tmp_path,monkeypatch):
    import reference_tables,sqlite3
    conn,p,data=setup;reference(tmp_path,monkeypatch)
    monkeypatch.setattr(reference_tables,'open_index',lambda *a:(_ for _ in ()).throw(sqlite3.OperationalError('synthetic permission failure')))
    status,result=api.handle(conn,'GET',f"/api/patients/{p['id']}/reference-matches",{},None)
    assert status==409 and result['review_status']=='reference_unavailable' and result['matches']==[]


def test_invalid_cached_page_is_not_a_crash_or_false_citation(tmp_path,monkeypatch):
    import reference_tables
    monkeypatch.setattr(db,'DATA_DIR',str(tmp_path/'data'));reference(tmp_path,monkeypatch)
    conn=reference_tables.open_index(library.current(),matches.anchors);conn.execute('UPDATE sections SET page_end=99999');conn.commit();conn.close()
    with pytest.raises(library.ReferenceUnavailable,match='pages are invalid'):
        matches.retrieve(context([evidence('notes','interview notes','Synthetic hydration')]))

def test_verified_comment_matches_and_unmatched_rows_are_listed_not_assessed(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DATA_DIR',str(tmp_path/'data'));reference(tmp_path,monkeypatch)
    base={'date':'2026-11-01','flags':[],'unit':'mL/min/1.73m2','reference_interval':'original range',
        'verified_by':'Synthetic Reviewer','verified_at':'2026-11-17T12:00:00'}
    commented=evidence('pathology:'+'c'*32,'pathology','eGFR: 41 | synthetic hydration noted',
        verification='named pharmacist verified',comment='synthetic hydration noted',**base)
    unverified=evidence('pathology:'+'d'*32,'pathology','eGFR: 40 | synthetic hydration noted',
        verification='UNVERIFIED: check original',comment='synthetic hydration noted',**base)
    plain=evidence('pathology:'+'e'*32,'pathology','Potassium: 4.1',
        verification='named pharmacist verified',comment='',**base)
    result=matches.retrieve(context([commented,unverified,plain]))
    ids={h['evidence']['id'] for h in result['matches']}
    assert commented['id'] in ids and unverified['id'] not in ids
    assert any('synthetic hydration' in h['matched_heading_words'] for h in result['matches'] if h['evidence']['id']==commented['id'])
    # Unmatched verified rows are reported as checked, never dropped or inferred.
    assert [e['id'] for e in result['unmatched_evidence']]==[plain['id']]
    assert result['unmatched_evidence'][0]['text']=='Potassium: 4.1'
    assert unverified['id'] in result['excluded_evidence_ids']

def test_comment_edit_and_removal_change_snapshot_and_matches(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DATA_DIR',str(tmp_path/'data'));reference(tmp_path,monkeypatch)
    base={'date':'2026-11-01','flags':[],'unit':'mL/min/1.73m2','reference_interval':'original range',
        'verified_by':'Synthetic Reviewer','verified_at':'2026-11-17T12:00:00',
        'verification':'named pharmacist verified'}
    # Test name chosen so no fixture heading matches it; only the comment can drive a match.
    with_comment=evidence('pathology:'+'c'*32,'pathology','Potassium: 4.1 | synthetic hydration noted',comment='synthetic hydration noted',**base)
    edited=evidence('pathology:'+'c'*32,'pathology','Potassium: 4.1 | fluid status reviewed',comment='fluid status reviewed',**base)
    removed=evidence('pathology:'+'c'*32,'pathology','Potassium: 4.1',comment='',**base)
    first=matches.retrieve(context([with_comment]))
    assert any('synthetic hydration' in h['matched_heading_words'] for h in first['matches'])
    second=matches.retrieve(context([edited]))
    assert not any('synthetic hydration' in h['matched_heading_words'] for h in second['matches'])
    third=matches.retrieve(context([removed]))
    assert third['matches']==[] and [e['id'] for e in third['unmatched_evidence']]==[removed['id']]
    # Each saved comment state produces a distinct evidence snapshot, so cached results cannot survive an edit.
    snaps={matches.retrieve(context([r]))['context_snapshot_sha256'] for r in [with_comment,edited,removed]}
    assert len(snaps)==3

def big_reference(tmp_path,monkeypatch,sections):
    path=tmp_path/'synthetic-big.pdf';doc=fitz.open()
    cover=doc.new_page();cover.insert_text((72,60),'Brainstorm synthetic test catalogue',fontname='hebo',fontsize=16)
    cover.insert_text((72,90),'Synthetic catalogue fixture only. No real reference or clinical recommendation is included.')
    for n in range(sections):
        p=doc.new_page()
        p.insert_text((72,60),'Synthetic hydration',fontname='hebo',fontsize=16)
        p.insert_text((72,90),'Synthetic hydration marker-%d passage text.'%n)
    tail=doc.new_page()
    tail.insert_text((72,60),'eGFR',fontname='hebo',fontsize=16)
    tail.insert_text((72,90),'eGFR synthetic source label only, not a threshold or clinical rule.')
    doc.save(path);doc.close()
    monkeypatch.setattr(db,'DATA_DIR',str(tmp_path/'data'))
    library.register({'path':str(path),'edition':'Synthetic big V1','local_use_confirmed':True});return path


def test_display_cap_row_with_unshown_matches_is_not_listed_unmatched(tmp_path,monkeypatch):
    big_reference(tmp_path,monkeypatch,25)
    hit=evidence('notes','interview notes','Synthetic hydration noted.')
    later=evidence('notes-later','interview notes','eGFR mentioned in the referral summary.')
    plain=evidence('obs','observation','Blood pressure 120 over 80 recorded.')
    result=matches.retrieve(context([hit,later,plain]))
    assert result['total_matches']>20 and len(result['matches'])==20 and result['truncated']
    # The later row's only hit sorts after display capacity is consumed: every shown
    # match belongs to the first row, yet the later row is still not reported unmatched.
    assert all(h['evidence']['id']==hit['id'] for h in result['matches'])
    assert [e['id'] for e in result['unmatched_evidence']]==[plain['id']]


def test_processing_cap_rows_beyond_200_are_not_reported_checked(tmp_path,monkeypatch):
    reference(tmp_path,monkeypatch)
    rows=[evidence('notes-%d'%n,'interview notes','Blood pressure reading %d.'%n) for n in range(200)]
    late=evidence('notes-late','interview notes','Synthetic hydration noted.')
    result=matches.retrieve(context(rows+[late]))
    assert result['processed_evidence_rows']==200 and result['truncated'] and result['total_matches']==0
    unmatched_ids=[e['id'] for e in result['unmatched_evidence']]
    assert len(unmatched_ids)==200 and late['id'] not in unmatched_ids
