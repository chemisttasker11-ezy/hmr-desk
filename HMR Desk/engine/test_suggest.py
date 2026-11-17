"""Synthetic offline suggestion checks."""
import json, os, tempfile, time
from pathlib import Path
import fitz
import api, brainstorm, db, jobs, report, suggest
with tempfile.TemporaryDirectory() as tmp:
 root=Path(tmp); refs=root/'skill'/'references'; refs.mkdir(parents=True); (root/'patient').mkdir()
 cases=[{'age':80,'meds':[{'kind':'current','row':['apixaban (Eliquis)']},{'kind':'current','row':['aspirin']}], 'pathology':[], 'findings':[{'title':'Apixaban aspirin bleeding','rec':'Review apixaban and aspirin','rationale':'Synthetic reason'}]} for i in range(8)]
 (refs/'case-index.jsonl').write_text('\n'.join(map(json.dumps,cases)),encoding='utf-8')
 (refs/'finding-library.md').write_text('## Anticoagulants\nApixaban aspirin bleeding',encoding='utf-8')
 (refs/'brainstorm-index.md').write_text('- bleeding and anticoagulant',encoding='utf-8')
 pdf=refs/'brainstorm-v2.pdf'
 doc=fitz.open(); page=doc.new_page()
 page.insert_text((72,72),'Apixaban',fontname='hebo',fontsize=16)
 page.insert_text((72,95),'Apixaban and aspirin increase bleeding risk. Review treatment carefully.')
 page.insert_text((72,150),'Metformin',fontname='hebo',fontsize=16)
 page.insert_text((72,175),'Metformin needs review in diabetes and reduced kidney function.')
 doc.save(pdf); doc.close()
 old_skill,old_base,old_data=jobs.SKILL,db.BASE,db.DATA_DIR
 jobs.SKILL=root/'skill'; db.BASE=str(root); db.DATA_DIR=str(root/'data')
 try:
  sections=brainstorm.sections(pdf); assert len(sections)==2 and [x['title'] for x in sections]==['Apixaban','Metformin'] and all(x['page']==1 for x in sections)
  cache=Path(db.DATA_DIR)/'brainstorm-sections-v2.json'; cached=cache.stat().st_mtime_ns
  assert brainstorm.sections(pdf)==sections and cache.stat().st_mtime_ns==cached
  os.utime(cache, ns=(cached-10000000000,cached-10000000000)); assert brainstorm.sections(pdf)==sections and cache.stat().st_mtime_ns == cached-10000000000
  idx=suggest.build_index(); assert len(idx['brainstorm_sections'])==2; assert suggest.normalise('Eliquis 5 mg tablet',idx['aliases'])=='apixaban'
  assert suggest.normalise('apixaban/aspirin 5 mg',idx['aliases'])=='apixaban/aspirin'
  keys=suggest.med_keys(['Eliquis','aspirin'],idx['mapping'],idx['aliases'])
  assert 'class:DOAC' in keys and 'combo:anticoagulant + antiplatelet' in keys
  assert idx['counts']['combo:anticoagulant + antiplatelet']==[8,8]
  context={'age':80,'meds':['Eliquis','aspirin'],'obs':'fall BP 100/60','labs':['eGFR 41'],'conditions':'','interactions':'apixaban aspirin'}
  assert {'topic:falls','topic:renal','topic:hypotension'} <= suggest.context_rules(context).keys()
  hits=suggest.suggest(context,idx); assert hits and len(hits)==1 and hits[0]['why'] and hits[0]['library']=='Anticoagulants'
  assert hits[0]['brainstorm']['title']=='Apixaban' and hits[0]['brainstorm']['page']==1 and 'Apixaban' in hits[0]['brainstorm']['snippet']
  assert all(x['why'] for x in hits) and len({(x['title'],x['rec']) for x in hits})==len(hits)
  simple={'age':80,'meds':['Eliquis','aspirin'],'obs':'','labs':[],'conditions':'','interactions':''}
  assert 'no eGFR on file' in suggest.suggest(simple,idx)[0]['missing']
  assert suggest.extractor(idx['mapping'],idx['aliases'])('apixaban bleeding') >= {'med:apixaban','class:DOAC','topic:bleeding'}
  assert 'no eGFR on file' in suggest.context_gaps({'obs':'','labs':[],'meds':[]})
  # mark the cached index stale (same old mtime) so a rebuild is visible by content, not by coarse Windows mtimes
  target=Path(db.DATA_DIR)/'suggest-index.json'; old=target.stat().st_mtime_ns; target.write_text('{"stale": 1}',encoding='utf-8'); os.utime(target,ns=(old,old))
  future=time.time()+2; os.utime(refs/'finding-library.md',(future,future)); assert 'stale' not in suggest.build_index()
  conn=db.connect(str(root/'db.sqlite')); conn.execute("INSERT INTO patients(key,name,folder) VALUES ('a','A','patient')"); conn.commit()
  status,result=api.handle(conn,'GET','/api/patients/1/suggestions',{},None)
  assert status==200 and set(result)=={'suggestions','context_gaps','context_snapshot_sha256'}
  status,result=api.handle(conn,'GET','/api/library',{'q':['metformin']},None)
  assert status==200 and any(x['source']=='Brainstorm V2 p.1' and x['title']=='Metformin' and 'Metformin' in x['snippet'] for x in result['results'])
  conn.close()
 finally: jobs.SKILL,db.BASE,db.DATA_DIR=old_skill,old_base,old_data
print('suggest self-check ok')
