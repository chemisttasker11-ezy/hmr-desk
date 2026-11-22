"""Prove real authenticated API route does not auto-verify pathology proposals.

Fixtures only: fictional PDF and a disposable encrypted test database.
"""
import fitz

import api
import db
import jobs
import pathology_records


def test_proposal_api_preview_and_accept_never_attests(tmp_path, monkeypatch):
    monkeypatch.setenv('HMR_DB', str(tmp_path / 'review.db'))
    monkeypatch.setattr(db, 'BASE', str(tmp_path))
    folder = tmp_path/'fictional_patient'
    folder.mkdir()
    monkeypatch.setattr(jobs, 'patient_folder', lambda p: folder)
    conn=db.connect()
    conn.execute(
        "INSERT INTO patients(key,name,state,is_test,folder) VALUES ('fictional','Fictional Person','confirmed',1,?)",
        (str(folder),))
    pid=conn.execute("SELECT id FROM patients WHERE key='fictional'").fetchone()[0]
    conn.commit()
    pdf=tmp_path/'fictional_pathology.pdf'
    with fitz.open() as doc:
        p=doc.new_page()
        p.insert_text((45,55),'Collection date: 12/11/2026')
        for x,t in [(45,'Test'),(220,'Result'),(350,'Units'),(485,'Reference')]:
            p.insert_text((x,100),t)
        for x,t in [(45,'Sodium'),(220,'139'),(350,'mmol/L'),(485,'135-145')]:
            p.insert_text((x,130),t)
        doc.save(pdf)
    get=lambda path:api.handle(conn,'GET',path,{},None)
    post=lambda path,body:api.handle(conn,'POST',path,{},body)
    status,imported=post(f'/api/patients/{pid}/pathology/sources',{'path':str(pdf)})
    assert status==200
    url=f'/api/patients/{pid}/pathology/sources/{imported["id"]}/proposals'
    status,generated=get(url)
    assert status==200,generated
    assert len(generated['proposals'])==1
    assert pathology_records.load(conn,{'id':pid})['records']==[]
    proposal=generated['proposals'][0]
    status,image=post(
       f'/api/patients/{pid}/pathology/sources/{imported["id"]}/proposal-image',
       {'proposal_id':proposal['id'],'source_sha256':imported['sha256']})
    assert status==200 and image['kind']=='row'
    status,accepted=post(url,{
        'proposal_id':proposal['id'],
        'source_sha256':imported['sha256'],
        'revision':generated['records_revision'],
        'fields':dict(proposal['fields']),
    })
    assert status==200,accepted
    assert accepted['record']['verified'] is False
    assert accepted['records']['verification']=={}
    assert accepted['record']['source'].endswith('cell:'+proposal['id'])
    assert len(pathology_records.load(conn,{'id':pid})['history'])==1
    assert get(url)[1]['records_revision']!=generated['records_revision']
    status,error=post(url,{
        'proposal_id':proposal['id'],'source_sha256':imported['sha256'],
        'revision':generated['records_revision'],'fields':dict(proposal['fields'])
    })
    assert status==409
    assert 'reload' in error['error']
