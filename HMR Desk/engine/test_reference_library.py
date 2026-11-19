"""Synthetic private-reference flow and fail-closed original-file checks."""
import hashlib,json
import fitz,pytest
import db,reference_library as r


def setup(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DATA_DIR',str(tmp_path/'local'))
    p=tmp_path/'reference.pdf';doc=fitz.open();a=doc.new_page()
    a.insert_text((72,72),'Brainstorm synthetic guide',fontsize=16,fontname='hebo')
    a.insert_text((72,110),'Synthetic catalogue context only. This text is a testing fixture with no medical facts.')
    a=doc.new_page();a.insert_text((72,100),'Synthetic continuation marker-alpha for verifying original physical page matching.')
    doc.save(p);doc.close();return p


def test_local_registration_search_open(tmp_path,monkeypatch):
    p=setup(tmp_path,monkeypatch)
    status=r.register({'path':str(p),'edition':'Synthetic test edition','local_use_confirmed':True})
    assert 'path' not in status and status['page_count']==2
    found=r.search('marker-alpha');assert len(found['results'])==1
    hit=found['results'][0];assert hit['page']==2 and hit['edition']=='Synthetic test edition'
    assert hit['review_status']=='pharmacist_review_required'
    assert r.open_source(status['pdf_sha256'],2)['path']==str(p)
    assert r.search('no-match')['results']==[]
    with pytest.raises(r.ReferenceUnavailable):r.open_source(status['pdf_sha256'],3)
    with pytest.raises(r.ReferenceUnavailable):r.open_source('0'*64,1)
    with pytest.raises(r.ReferenceUnavailable):r.open_source(status['pdf_sha256'],True)
    p.write_bytes(p.read_bytes()+b'\nchanged')
    with pytest.raises(r.ReferenceUnavailable):r.search('marker-alpha')
    with pytest.raises(r.ReferenceUnavailable):r.open_source(status['pdf_sha256'],2)


def test_no_permission_no_registry_and_symlink_refused(tmp_path,monkeypatch):
    p=setup(tmp_path,monkeypatch)
    with pytest.raises(r.ReferenceUnavailable):r.register({'path':str(p),'edition':'test','local_use_confirmed':False})
    assert not r.registry_path().exists()
    with pytest.raises(r.ReferenceUnavailable):r.current()


def test_symlink_reference_refused(tmp_path,monkeypatch):
    p=setup(tmp_path,monkeypatch)
    link=tmp_path/'link.pdf'
    try:link.symlink_to(p)
    except (OSError,NotImplementedError) as exc:
        pytest.skip('Cannot create a symlink here ('+type(exc).__name__+'; Windows needs admin or Developer Mode): symlink refusal NOT tested on this machine')
    with pytest.raises(r.ReferenceUnavailable):r.inspect(link)
    with pytest.raises(r.ReferenceUnavailable):r.current()


def test_terms_cannot_match_across_different_physical_pages(tmp_path,monkeypatch):
    p=setup(tmp_path,monkeypatch)
    r.register({'path':str(p),'edition':'test','local_use_confirmed':True})
    assert r.search('catalogue marker-alpha')['results']==[]


def test_production_api_independent_reference_routes(tmp_path,monkeypatch):
    import api
    p=setup(tmp_path,monkeypatch)
    # Hermetic: a build tree that has packaged Brainstorm tables must not turn the missing-PDF case into the packaged-tier 200.
    monkeypatch.setattr(api.app_paths,'engine_assets',lambda:tmp_path/'no-packaged-tables')
    status,result=api.handle(None,'POST','/api/reference/local',{}, {'path':str(p),'edition':'test','local_use_confirmed':True})
    assert status==200
    status,found=api.handle(None,'GET','/api/reference/search',{'q':['marker-alpha']},None)
    assert status==200 and found['results'][0]['page']==2
    status,opened=api.handle(None,'POST','/api/reference/open',{}, {'pdf_sha256':result['pdf_sha256'],'page':2})
    assert status==200 and opened['page']==2
    p.unlink()
    status,missing=api.handle(None,'GET','/api/reference/search',{'q':['marker-alpha']},None)
    assert status==409 and 'unavailable' in missing['error']


def test_fabricated_cache_excerpt_cannot_become_source_quote(tmp_path,monkeypatch):
    import brainstorm
    p=setup(tmp_path,monkeypatch)
    r.register({'path':str(p),'edition':'test','local_use_confirmed':True})
    sections=brainstorm.sections(p)
    sections[0]['text']='fabricated-marker in cache, not original page'
    sections[0]['fragments']=[{'page':1,'text':sections[0]['text']}];sections[0]['page_end']=1
    monkeypatch.setattr(brainstorm,'sections',lambda path:sections)
    with pytest.raises(r.ReferenceUnavailable,match='cannot be verified'):r.search('fabricated-marker')


def test_malformed_registry_and_nonexistent_registration_fail_cleanly(tmp_path,monkeypatch):
    setup(tmp_path,monkeypatch)
    r.registry_path().parent.mkdir(parents=True,exist_ok=True);r.registry_path().write_text('[]')
    with pytest.raises(r.ReferenceUnavailable):r.current()
    with pytest.raises(r.ReferenceUnavailable):r.register({'path':str(tmp_path/'missing.pdf'),'edition':'test','local_use_confirmed':True})
