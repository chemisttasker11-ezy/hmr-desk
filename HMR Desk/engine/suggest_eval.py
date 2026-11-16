"""Measure held-out medicine/topic coverage without printing patient data."""
import collections, json, statistics
import brainstorm, jobs, report, suggest

def evaluate(train, held, library, brainstorm_text, tuning, sections):
 index=suggest.make_index(train,library,brainstorm_text,tuning=tuning,brainstorm_sections=sections)
 extract=suggest.extractor(index['mapping'],index['aliases'])
 covered=[0,0,0]; total=0; no_key=0; missing=collections.Counter()
 for case in held:
  suggestions=suggest.suggest(suggest.case_context(case),index)
  ranked=[extract(x['title']+' '+x['rec']) for x in suggestions]
  for finding in case.get('findings',[]):
   keys=extract(finding.get('title','')+' '+finding.get('rec',''))
   meds={k for k in keys if k.startswith(('med:','class:'))}
   relevant=meds or {k for k in keys if k.startswith('topic:')}
   total+=1
   if not relevant: no_key+=1; continue
   for i,n in enumerate((5,10,15)):
    if any(relevant & x for x in ranked[:n]): covered[i]+=1
   if not any(relevant & x for x in ranked[:15]): missing.update(relevant)
 return total,no_key,covered,missing,index

def main():
 refs=jobs.SKILL/'references'; cases=[json.loads(x) for x in report._read(refs/'case-index.jsonl').splitlines() if x.strip()]
 train=[c for i,c in enumerate(cases) if i%5]; held=[c for i,c in enumerate(cases) if i%5==0]
 library=report._read(refs/'finding-library.md'); brainstorm_text=report._read(refs/'brainstorm-index.md')
 sections=brainstorm.sections(refs/'brainstorm-v2.pdf')
 print('Reports:',len(held),'mean real findings:',round(statistics.mean(len(c.get('findings',[])) for c in held),2),flush=True)
 print('Pass | No key | @5 | @10 | @15',flush=True)
 results=[]
 for label,tuning in [('Before',0),('Pass 1',1),('Pass 2',2)]:
  total,no,covered,missing,index=evaluate(train,held,library,brainstorm_text,tuning,sections); results.append((covered[-1],covered[0],tuning))
  print(label+' | '+' | '.join(f'{x/total:.1%}' for x in [no]+covered),flush=True)
  if tuning==1:
   print('Uncovered keys:', ', '.join(f'{k} ({n})' for k,n in missing.most_common(15)),flush=True)
   frequencies=collections.Counter()
   for c in cases:
    frequencies.update({k[4:] for k in suggest.med_keys(suggest.case_context(c)['meds'],index['mapping'],index['aliases']) if k.startswith('med:')})
   unmatched=[(m,n) for m,n in frequencies.items() if not any(m==g or m.startswith(g+' ') for g in index['mapping'])]
   print('Class mappings:',len(index['mapping']),'; unmapped distinct medicines:',len(unmatched),'; unmapped patient-medicine occurrences:',sum(n for m,n in unmatched),'; all occurrences:',sum(frequencies.values()),flush=True)
 print('Best @15 pass:',max(results)[2],flush=True)
if __name__=='__main__': main()
