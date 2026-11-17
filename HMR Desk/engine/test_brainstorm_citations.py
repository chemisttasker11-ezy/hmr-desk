"""Synthetic page citation checks. No supplied reference contents or clinical rules."""
import hashlib
import fitz
import brainstorm
import db


def pdf(tmp_path):
    path = tmp_path/'synthetic-reference.pdf'
    doc=fitz.open()
    p=doc.new_page();p.insert_text((72,72),'Repeated medicine heading',fontname='hebo',fontsize=16)
    p.insert_text((72,100),'First page context only, enough text to preserve this section.')
    p=doc.new_page();p.insert_text((72,100),'Continuation contains synthetic-marker-alpha and a long source sentence.')
    p=doc.new_page();p.insert_text((72,72),'Repeated medicine heading',fontname='hebo',fontsize=16)
    p.insert_text((72,100),'Different context contains synthetic-marker-beta and separate wording.')
    doc.save(path);doc.close()
    return path


def test_continuation_quote_points_to_actual_physical_page(tmp_path, monkeypatch):
    monkeypatch.setattr(db,'DATA_DIR',str(tmp_path/'cache'))
    path=pdf(tmp_path);sections=brainstorm.sections(path)
    assert len(sections)==2
    hit=brainstorm.passage(sections[0],['synthetic-marker-alpha'])
    assert hit['page']==2 and hit['section_page']==1 and hit['section_page_end']==2
    assert hit['pdf_sha256']==hashlib.sha256(path.read_bytes()).hexdigest()
    assert hit['citation_version']==1 and hit['review_status']=='pharmacist_review_required'
    with fitz.open(path) as doc: assert hit['snippet'] in doc[hit['page']-1].get_text()
    assert brainstorm.passage(sections[0],['synthetic-marker-beta']) is None


def test_repeated_headings_keep_independent_context_and_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(db,'DATA_DIR',str(tmp_path/'cache'))
    path=pdf(tmp_path);sections=brainstorm.sections(path)
    assert sections[0]['title']==sections[1]['title']
    hit=brainstorm.passage(sections[1],['synthetic-marker-beta'])
    assert hit['page']==3 and hit['section_page']==3
    assert 'alpha' not in hit['snippet']
    assert brainstorm.sections(path)==sections
    assert brainstorm.passage({'title':'legacy','page':1,'text':'synthetic-marker-alpha'},['alpha']) is None
    assert brainstorm.passage(sections[0],[]) is None


def test_existing_library_uses_quote_page_not_heading_start(tmp_path,monkeypatch):
    import jobs,report
    path=pdf(tmp_path)
    refs=tmp_path/'assets'/'references';refs.mkdir(parents=True)
    path.replace(refs/'brainstorm-v2.pdf')
    monkeypatch.setattr(db,'DATA_DIR',str(tmp_path/'cache'))
    monkeypatch.setattr(jobs,'SKILL',refs.parent)
    hits=report.library('synthetic-marker-alpha')
    assert len(hits)==1 and hits[0]['page']==2
    assert hits[0]['source']=='Brainstorm V2 p.2'
    assert hits[0]['section_page']==1 and hits[0]['section_page_end']==2
    assert len(hits[0]['pdf_sha256'])==64


def test_malformed_cache_is_rebuilt_from_original(tmp_path,monkeypatch):
    import json
    monkeypatch.setattr(db,'DATA_DIR',str(tmp_path/'cache'))
    path=pdf(tmp_path);first=brainstorm.sections(path)
    cache=tmp_path/'cache'/'brainstorm-sections-v3.json'
    broken=json.loads(cache.read_text());broken['sections'][0]['fragments']=[{'page':'invented','text':'unverified'}]
    cache.write_text(json.dumps(broken))
    assert brainstorm.sections(path)==first


def test_malformed_citation_fields_fail_closed(tmp_path,monkeypatch):
    import copy
    monkeypatch.setattr(db,'DATA_DIR',str(tmp_path/'cache'))
    section=brainstorm.sections(pdf(tmp_path))[0]
    for key,value in [('pdf_sha256','invalid'),('page_end',0),('page',True),('fragments',[None]),('citation_version',0)]:
        broken=copy.deepcopy(section);broken[key]=value
        assert brainstorm.passage(broken,['synthetic-marker-alpha']) is None


def test_excerpt_omissions_are_explicit_and_text_stays_within_page():
    text=('beginning '*25)+'target-match '+('ending '*80)
    s={'title':'Synthetic','page':1,'page_end':1,'fragments':[{'page':1,'text':text}],'pdf_sha256':'a'*64,'citation_version':1}
    hit=brainstorm.passage(s,['target-match'])
    assert hit['snippet'] in text and len(hit['snippet'])<=300
    assert hit['omitted_before'] and hit['omitted_after']
    assert 'target-match' in hit['snippet']


def test_structured_marker_mode_keeps_inline_bold_body_emphasis(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DATA_DIR',str(tmp_path/'cache'));path=tmp_path/'markers.pdf';doc=fitz.open();p=doc.new_page()
    marker=(0,166/255,237/255)
    p.insert_text((40,40),'Synthetic actual heading',color=marker)
    p.insert_text((40,70),'Beginning source body, enough original text to retain this section.')
    p.insert_text((40,100),'An emphasised interval is body text',fontname='hebo')
    p.insert_text((40,130),'Continuation still belongs to the original marked heading.')
    p.insert_text((40,170),'Synthetic second heading',color=marker)
    p.insert_text((40,200),'Second original body, independently indexed and page-linked.')
    doc.save(path);doc.close()
    sections=brainstorm.sections(path,True)
    assert len(sections)==2 and 'emphasised interval' in sections[0]['text']
    assert sections[0]['title']=='Synthetic actual heading'
    assert all('emphasised interval' not in s['title'] for s in sections)
    # Separate cache means existing manual/legacy parser results are not substituted.
    assert len(brainstorm.sections(path))==3
