"""Offline, frequency-based prompts from the local de-identified case index."""
import collections
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

import brainstorm
import db
import interview
import jobs
import records
import report

CLASSES_PATH = Path(__file__).with_name('drug_classes.json')
TOPICS = {
 'renal': r'\b(?:renal|kidney|egfr|creatinine)\b', 'falls': r'\b(?:falls?|falling)\b',
 'hypotension': r'\b(?:hypotension|orthostatic|postural|low blood pressure)\b',
 'bleeding': r'\b(?:bleed\w*|haemorrhag\w*)\b', 'hypoglycaemia': r'\b(?:hypoglyc\w*|hypoglyc[ae]mi\w*)\b',
 'sedation': r'\b(?:sedat\w*|drows\w*)\b', 'anticholinergic burden': r'\banticholinergic\b',
 'adherence': r'\b(?:adherence|compliance|dose administration aid|daa|webster)\b',
 'inhaler technique': r'\b(?:inhaler technique|inhaler device|inhaler use)\b',
 'vaccination': r'\b(?:vaccin\w*|immunis\w*)\b', 'bone health': r'\b(?:osteoporosis|fractur\w*|bone health|bone density)\b',
 'B12': r'\b(?:b12|cobalamin)\b', 'lipid target': r'\b(?:lipid\w*|cholesterol|ldl)\b',
 'deprescribing': r'\b(?:deprescrib\w*|taper\w*|ceas\w*|discontinu\w*)\b',
 'polypharmacy': r'\b(?:polypharmacy|multiple medicines)\b', 'blood pressure': r'\b(?:blood pressure|hypertension|\bbp\b)\b',
 'diabetes': r'\b(?:diabetes|glycaemi\w*|hba1c)\b', 'pain': r'\b(?:pain|analgesi\w*)\b',
}
COMBOS = [('anticoagulant','antiplatelet'), ('opioid','benzodiazepine'), ('ACE inhibitor','diuretic','NSAID'), ('ARB','diuretic','NSAID')]
SYNONYMS = {'DOAC':r'\b(?:doacs?|direct oral anticoagulants?)\b','PPI':r'\b(?:ppis?|proton pump inhibitors?)\b','NSAID':r'\b(?:nsaids?|non.steroidal anti.inflammator\w*)\b','ARB':r'\b(?:arbs?|angiotensin receptor blockers?)\b','ACE inhibitor':r'\b(?:ace inhibitors?)\b','SSRI':r'\b(?:ssris?|selective serotonin reuptake inhibitors?)\b','SNRI':r'\b(?:snris?)\b'}
PRIVACY = re.compile(r'(?i)\b(?:mr|mrs|ms|miss|dr)\.?\s+(?!\[pt\])[A-Z][a-z]+|\b(?:dob|date of birth|born)\b')

def classes():
 return json.loads(CLASSES_PATH.read_text(encoding='utf-8'))

def clean(text):
 text = text.casefold().strip().replace('–','-')
 text = re.sub(r'\([^)]*\)', '', text)
 text = re.sub(r'\b\d+(?:[.,]\d+)?\s*(?:mg|mcg|micrograms?|g|ml|iu|units?|%)\b', '', text)
 text = re.split(r'\s+\b(?:tablet|capsule|inhaler|injection|cream|ointment|patch|spray|drops|daily|once|twice)\b|\s+\d', text, 1)[0]
 text = re.sub(r'\b(?:modified.release|extended.release|controlled.release|mr|xr|sr|ir|ec|xl|inhaler|osteo|tartrate|succinate|arginine)\b', '', text)
 return re.sub(r'\s+', ' ', text).strip(' -.,')

def aliases_for(cases, mapping):
 aliases = {}
 votes = collections.defaultdict(collections.Counter)
 for case in cases:
  for med in case.get('meds', []):
   row = med.get('row', []); raw = row[0] if row else ''
   for inside in re.findall(r'\(([^()]*)\)', raw):
    left, right = clean(raw.split('(')[0]), clean(inside)
    left_known = any(x in mapping for x in re.split(r'\s*[/+]\s*',left))
    right_known = any(x in mapping for x in re.split(r'\s*[/+]\s*',right))
    if left and right and left_known != right_known:
     brand, generic = (right,left) if left_known else (left,right)
     if len(brand)>2: votes[brand][generic] += 1
 for brand, counts in votes.items():
  if len(counts)==1: aliases[brand] = counts.most_common(1)[0][0]
 return aliases

def normalise(med_text, aliases=None):
 name = clean(med_text)
 aliases = aliases if aliases is not None else _default_aliases()
 name = aliases.get(name, name)
 return '/'.join(x.strip() for x in re.split(r'\s*[/+]\s*', name) if x.strip())

_alias_cache = None
def _default_aliases():
 global _alias_cache
 if _alias_cache is None:
  path = jobs.SKILL / 'references' / 'case-index.jsonl'
  cases = [json.loads(x) for x in report._read(path).splitlines() if x.strip()]
  _alias_cache = aliases_for(cases, classes())
 return _alias_cache

def med_keys(meds, mapping, aliases):
 keys = set()
 for text in meds:
  for name in normalise(text, aliases).split('/'):
   if not name or name in ('ml','mg','mcg','g','dose','unit','units'): continue
   keys.add('med:'+name)
   for generic, cls in mapping.items():
    if name == generic or name.startswith(generic+' '):
     keys.update('class:'+x for x in cls)
 for combo in COMBOS:
  if all('class:'+x in keys for x in combo): keys.add('combo:'+' + '.join(combo))
 return keys

def extractor(mapping, aliases, tuning=2):
 names = sorted(set(mapping) | set(aliases), key=len, reverse=True)
 pattern = re.compile(r'(?<!\w)('+'|'.join(re.escape(x) for x in names)+r')(?!\w)',re.I) if names else None
 def extract(text):
  found = set()
  if pattern:
   for match in pattern.finditer(text): found.update(med_keys([match.group()],mapping,aliases))
  for cls in {c for group in mapping.values() for c in group}:
   rx = SYNONYMS.get(cls, r'(?<!\w)'+re.escape(cls)+r's?(?!\w)')
   if re.search(rx,text,re.I): found.add('class:'+cls)
  for topic, rx in TOPICS.items():
   if tuning == 0 and topic in ('polypharmacy','blood pressure','diabetes','pain'): continue
   if tuning == 1 and topic in ('diabetes','pain'): continue
   if re.search(rx,text,re.I): found.add('topic:'+topic)
  for combo in COMBOS:
   if all('class:'+x in found for x in combo): found.add('combo:'+' + '.join(combo))
  return found
 return extract

def context_rules(context):
 out = {}
 # New production evidence path has no unsourced numeric or age cutoffs.
 # Compatibility case-index evaluation below is not approved clinical logic.
 if context.get('evidence_version') == 1: return out
 try:
  if int(context.get('age') or 0)>=75: out['topic:falls']='age '+str(context['age'])
 except (ValueError, TypeError): pass
 text = ' '.join([str(context.get('obs','')),str(context.get('conditions',''))]+list(context.get('labs',[])))
 m = re.search(r'\begfr\s*[:=]?\s*(?![<>])([0-9]+(?:\.[0-9]+)?)\b',text,re.I)
 if m and float(m[1])<60: out['topic:renal']='eGFR '+m[1]
 if re.search(r'\bfall\w*\b',str(context.get('obs',''))+' '+str(context.get('conditions','')),re.I): out['topic:falls']='falls noted'
 bp = re.search(r'\b(?:bp|blood pressure)\s*[:=]?\s*(\d{2,3})\s*/\s*\d+',text,re.I)
 if bp and int(bp[1])<110: out['topic:hypotension']='BP '+bp[0].split()[-1]
 if len(context.get('meds',[]))>=10: out['topic:polypharmacy']=str(len(context['meds']))+' medicines listed'
 return out

def case_context(case):
 return {'age':case.get('age'), 'sex':case.get('sex',''), 'meds':[m['row'][0] for m in case.get('meds',[]) if m.get('row') and m.get('kind','').lower() not in ('ceased','stopped') and not re.search(r'\b(?:ceased|stopped|not currently using)\b', ' '.join(m['row'][1:]), re.I)], 'conditions':case.get('Current Conditions',''), 'obs':case.get('Obs from interview',''), 'labs':case.get('pathology',[]), 'interactions':''}

def make_index(cases, library_text, brainstorm_text, mapping=None, tuning=1, brainstorm_sections=None):
 mapping = mapping or classes(); aliases = aliases_for(cases,mapping); extract = extractor(mapping,aliases,tuning)
 lib=[]
 for section in re.split(r'(?m)(?=^## )',library_text):
  if section.startswith('## '):
   title = section.partition('\n')[0][3:].strip(); lib.append({'title':title,'keys':sorted(extract(section))})
 brainstorm=[{'line':line.strip(), 'keys':sorted(extract(line))} for line in brainstorm_text.splitlines() if line.strip() and not line.startswith('#')]
 counts=collections.defaultdict(lambda:[0,0]); findings=[]
 for case in cases:
  context=case_context(case); exposure=med_keys(context['meds'],mapping,aliases) | set(context_rules(context))
  exposure |= {k for k in extract(context['conditions']+' '+context['obs']+' '+' '.join(context['labs'])) if k.startswith('topic:')}
  case_findings=[]; carrying=set()
  for f in case.get('findings',[]):
   fields={k:str(f.get(k,'')) for k in ('title','rec','rationale')}
   if PRIVACY.search(' '.join(fields)) or PRIVACY.search(str(case.get('Current Conditions',''))): continue
   keys=extract(fields['title']+' '+fields['rec'])
   # Topic exposure includes patients whose own observations/conditions mention the topic.
   carrying |= keys
   case_findings.append({**fields,'keys':sorted(keys),'exposure':sorted(exposure), 'age':context['age']})
  for key in exposure:
   counts[key][0]+=1
   if key in carrying: counts[key][1]+=1
  findings.extend(case_findings)
 return {'version':2,'mapping':mapping,'aliases':aliases,'counts':dict(counts),'findings':findings,'library':lib,'brainstorm':brainstorm,'brainstorm_sections':[{**section, 'keys':sorted(k for k in extract(section['title']+' '+section['text']) if k.startswith(('med:', 'class:', 'topic:')))} for section in (brainstorm_sections or [])],'tuning':tuning}

class LibraryUnavailable(ValueError):
 """Required reviewed local reference inputs are unavailable; never invent a corpus."""

INDEX_ALGORITHM_VERSION = 3

def build_index():
 refs=jobs.SKILL/'references'
 paths=[refs/'case-index.jsonl',refs/'finding-library.md',refs/'brainstorm-index.md',CLASSES_PATH]
 pdf=refs/'brainstorm-v2.pdf'
 try:
  if any(not p.is_file() for p in paths): raise LibraryUnavailable()
  if pdf.is_file(): paths.append(pdf)
  # Frozen Python modules live in an archive. Never stat __file__ as a cache dependency.
  source_hash=hashlib.sha256(str(INDEX_ALGORITHM_VERSION).encode())
  for p in paths:
   source_hash.update(p.name.encode()); source_hash.update(p.read_bytes())
  source_key=source_hash.hexdigest()
  target=Path(db.DATA_DIR)/'suggest-index.json'
  if target.is_file():
   try:
    cached=json.loads(target.read_text(encoding='utf-8'))
    if cached.get('source_sha256')==source_key: return cached
   except (ValueError, OSError, AttributeError): pass
  cases=[json.loads(x) for x in paths[0].read_text(encoding='utf-8').splitlines() if x.strip()]
  if not cases: raise LibraryUnavailable()
  idx=make_index(cases,paths[1].read_text(encoding='utf-8'),paths[2].read_text(encoding='utf-8'),brainstorm_sections=brainstorm.sections(pdf))
  idx['source_sha256']=source_key
  target.parent.mkdir(parents=True,exist_ok=True)
  fd,tmp=tempfile.mkstemp(dir=target.parent,prefix='suggest-',suffix='.tmp')
  try:
   with os.fdopen(fd,'w',encoding='utf-8') as f: json.dump(idx,f,ensure_ascii=False)
   os.replace(tmp,target)
  finally:
   if os.path.exists(tmp): os.unlink(tmp)
  return idx
 except LibraryUnavailable: raise
 except (OSError, ValueError, TypeError, KeyError, AttributeError):
  raise LibraryUnavailable() from None

def suggest(context, index=None):
 index=index or build_index(); mapping=index['mapping']; aliases=index['aliases']; extract=extractor(mapping,aliases,index.get('tuning',2))
 patient=med_keys(context.get('meds',[]),mapping,aliases); rules=context_rules(context); keys=patient | set(rules)
 notes=str(context.get('obs',''))+' '+str(context.get('conditions',''))+' '+' '.join(context.get('labs',[]))
 tags={x for x in extract(notes) if x.startswith('topic:')}; keys |= tags
 interaction=str(context.get('interactions','')); interaction_lines=[extract(line)&patient for line in interaction.splitlines()]
 scores=[]
 for key in keys:
  exposed,with_finding=index['counts'].get(key,[0,0])
  if exposed<5 or not with_finding: continue
  score=with_finding/exposed
  if index.get('tuning',2)>=1 and key in rules: score+=0.01
  if index.get('tuning',1)>=1 and key.startswith('combo:') and any(all('class:'+c in line for c in key[6:].split(' + ')) for line in interaction_lines): score+=0.01
  scores.append((score,key,exposed,with_finding))
 scores.sort(key=lambda x:(-x[0],x[1])); result=[]; seen=set()
 for score,key,exposed,count in scores:
  choices=[]
  for f in index['findings']:
   if key not in f['keys']: continue
   shared=len(patient & set(f['exposure']))
   try: age=int(context.get('age') or 0); old=int(f.get('age') or 0); close=bool(age and old and abs(age-old)<=10)
   except (ValueError,TypeError): close=False
   overlap=len(tags & set(f['keys'])); choices.append((shared+int(close)+overlap,f))
  choices.sort(key=lambda x:-x[0])
  if not choices: continue
  f=choices[0][1]; identity=(f['title'],f['rec'],f['rationale'])
  if identity in seen: continue
  seen.add(identity)
  label=key.split(':',1)[1]; reason=rules.get(key) or ('takes medicines in these classes together: '+label if key.startswith('combo:') else 'listed medicine or class: '+label if not key.startswith('topic:') else 'context mentions '+label)
  if key.startswith('combo:'):
   names=[]
   for cls in key[6:].split(' + '):
    match=next((normalise(m,aliases) for m in context.get('meds',[]) if 'class:'+cls in med_keys([m],mapping,aliases)),None)
    if match and match not in names: names.append(match)
   if names: reason='Takes '+ ' and '.join(names)+' together.'
  why=[reason, f'Raised in {count} of {exposed} past patients with this key.']
  supporting=[]
  if context.get('evidence_version') == 1:
   for e in context['evidence']:
    if not e['eligible']: continue
    ekeys=med_keys([e['text']],mapping,aliases) if e['kind']=='medicine' else extract(e['text'])
    relevant_keys=({key} | set(f['keys']) | (set('class:'+x for x in key[6:].split(' + ')) if key.startswith('combo:') else set()))
    if relevant_keys & ekeys: supporting.append(e)
   reason=('Medicine/class text match: ' if not key.startswith('topic:') else 'Topic text match, not an asserted finding: ')+label
   why=[reason, f'Template appeared in {count} of {exposed} indexed past cases with this key; not a probability or guideline.', 'Check original evidence, negation, history and current relevance. Past-case wording may not apply.']
  missing=[]
  if (key.startswith('med:') or key.startswith('class:') or key=='topic:renal') and not re.search(r'\begfr\b',notes,re.I): missing.append('no eGFR on file')
  if key in ('topic:hypotension','topic:blood pressure') and not re.search(r'\b(?:bp|blood pressure)\b',notes,re.I): missing.append('no BP recorded')
  if context.get('evidence_version') == 1:
   missing=['Clinical relevance and original context require pharmacist review']
   for e in supporting:
    missing.extend(e['id']+': '+flag for flag in e.get('flags',[]))
    if e['kind']=='medicine' and e.get('use_status') not in ('taking','prn'):
     missing.append(e['id']+': actual use is not established')
  lib=next((x['title'] for x in index['library'] if key in x['keys']),'')
  relevant={key} | set(f['keys'])
  matches=[(len(relevant & set(section['keys'])), section) for section in index.get('brainstorm_sections', [])]
  matches=[(n, section) for n, section in matches if n]
  brain=None
  if matches:
   _, section=min(matches, key=lambda x:(-x[0],len(x[1]['text'])))
   shared=relevant & set(section['keys']); patterns=[]
   for item in shared:
    kind, value=item.split(':',1)
    if kind=='topic': patterns.append(TOPICS[value])
    elif kind=='class': patterns.append(SYNONYMS.get(value, r'(?<!\w)'+re.escape(value)+r's?(?!\w)'))
    elif kind=='med': patterns.append(r'(?<!\w)'+re.escape(value)+r'(?!\w)')
   brain={'title':section['title'],'page':section['page'],'snippet':brainstorm.snippet(section['text'],patterns)}
  elif not index.get('brainstorm_sections'):
   line=next((x['line'] for x in index['brainstorm'] if key in x['keys']),None)
   if line: brain={'title':line,'page':None,'snippet':line[:300]}
  alternatives=[]
  for _,other in choices[1:]:
   if (other['title'],other['rec'],other['rationale']) != identity:
    alternatives.append({k:other[k] for k in ('title','rec','rationale')})
    if len(alternatives)==2: break
  result.append({**{k:f[k] for k in ('title','rec','rationale')},'source':'past cases','why':why,'missing':missing,'alternatives':alternatives,'library':lib,'brainstorm':brain,'key':key})
  if context.get('evidence_version') == 1:
   result[-1].update(evidence=supporting, context_snapshot_sha256=context['context_snapshot_sha256'], review_status='pharmacist_review_required')
  if len(result)==15: break
 return result

def context_for(conn, patient):
 import suggestion_context
 return suggestion_context.build(conn,patient)

def context_gaps(context):
 if context.get('evidence_version') == 1: return context['context_gaps']
 gaps=[]; text=context.get('obs','')+' '+' '.join(context.get('labs',[]))
 if not context.get('meds'): gaps.append('no medicines on file')
 if not context.get('age'): gaps.append('no age on file')
 if not re.search(r'\begfr\b',text,re.I): gaps.append('no eGFR on file')
 if not re.search(r'\b(?:bp|blood pressure)\b',text,re.I): gaps.append('no BP recorded')
 if not context.get('interactions'): gaps.append('no interactions text on file')
 return gaps
