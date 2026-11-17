const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(require.resolve('../renderer/reference-matches.js'),'utf8');
function response(){return {reference:{edition:'Synthetic V1',pdf_sha256:'a'.repeat(64)},checked_on:'2026-11-17',method:'Literal heading text overlap only',processed_evidence_rows:1,total_matches:1,truncated:false,context_gaps:['Date not established'],context_snapshot_sha256:'context-one',matches:[{evidence:{id:'notes',kind:'interview notes',text:'Denies synthetic hydration <script>historical</script>',source:'interview.json/notes',date:'',flags:['Date not established'],verification:'recorded text'},matched_heading_words:['synthetic hydration'],reference:{title:'Synthetic hydration',edition:'Synthetic V1',page:2,section_page:1,section_page_end:2,snippet:'Synthetic hydration original quote',pdf_sha256:'a'.repeat(64)}}]};}
function harness(){
 const target={textContent:'',innerHTML:'',isConnected:true};const calls=[],opens=[],handlers={};let dirty=false;
 const ctx={H:require('../renderer/helpers'),page:'interview',interviewId:'1',reportId:'2',interviewConflict:false,interviewPathologyDirty:false,interviewDirty:()=>dirty,document:{getElementById:()=>target,addEventListener:(name,fn)=>handlers[name]=fn},hmr:{api:async(...args)=>{calls.push(args);return response()},openLocalReference:async(...args)=>opens.push(args)}};
 vm.createContext(ctx);vm.runInContext(source,ctx);
 const click=async(index='0')=>handlers.click({target:{closest:()=>({hasAttribute:()=>false,dataset:{evidenceReferenceOpen:index}})}});
 return {ctx,target,calls,opens,setDirty:v=>dirty=v,click};
}
test('source-linked original negation/uncertainty and exact citation are escaped, no advice insert',()=>{
 const h=harness(),html=h.ctx.evidenceReferenceHtml(response());assert.match(html,/Denies synthetic hydration &lt;script&gt;/);assert.doesNotMatch(html,/<script>/);assert.match(html,/not assert the condition is present/);assert.match(html,/Physical PDF page 2/);assert.match(html,/Section pages 1-2/);assert.match(html,/Pharmacist review required/);assert.doesNotMatch(html,/data-suggestion-add|data-library-insert/);
});
test('automatic GET loads current saved evidence without past-case endpoint',async()=>{
 const h=harness();await h.ctx.refreshEvidenceReferences();assert.equal(h.calls[0][1],'/api/patients/1/reference-matches');assert.match(h.target.innerHTML,/Original interview notes/);assert.equal(h.calls.length,1);
 await h.click();assert.equal(h.calls.length,2);assert.deepEqual(h.opens[0],['a'.repeat(64),2]);
});
test('dirty local interview/pathology never exposes or opens old matches',async()=>{
 const h=harness();h.setDirty(true);await h.ctx.refreshEvidenceReferences();assert.equal(h.calls.length,0);assert.match(h.target.textContent,/Save and refresh/);
 h.setDirty(false);await h.ctx.refreshEvidenceReferences();h.ctx.interviewPathologyDirty=true;await h.click();assert.equal(h.opens.length,0);
});
test('changed evidence revision or reference prevents opening, asks re-review',async()=>{
 for(const mutate of [r=>r.context_snapshot_sha256='changed',r=>r.reference.pdf_sha256='b'.repeat(64),r=>r.reference.edition='new edition']){
 const h=harness();await h.ctx.refreshEvidenceReferences();h.ctx.hmr.api=async()=>{const r=response();mutate(r);return r};await h.click();assert.equal(h.opens.length,0);assert.match(h.target.textContent,/Refresh and re-review/);
 }
});
test('delayed response for prior patient or invalidated state is discarded',async()=>{
 const h=harness();let finish;h.ctx.hmr.api=()=>new Promise(resolve=>finish=resolve);const pending=h.ctx.refreshEvidenceReferences();h.ctx.interviewId='other';finish(response());await pending;assert.equal(h.target.innerHTML,'');
 const second=h.ctx.refreshEvidenceReferences();h.ctx.invalidateEvidenceReferences();finish(response());await second;assert.equal(h.target.innerHTML,'');
});
test('unavailable reference stays distinct from no match and has no generation claim',async()=>{
 const h=harness();h.ctx.hmr.api=async()=>{throw Error('Register local PDF')};await h.ctx.refreshEvidenceReferences();assert.match(h.target.textContent,/Register local PDF/);assert.match(h.target.textContent,/No evidence-linked reference passages were generated/);
});
test('interview/report integration invalidates edits and loads on saved render',()=>{
 const interview=fs.readFileSync(require.resolve('../renderer/interview.js'),'utf8');const report=fs.readFileSync(require.resolve('../renderer/report-editor.js'),'utf8');const index=fs.readFileSync(require.resolve('../index.html'),'utf8');assert.match(interview,/function interviewChanged\(field\) \{\s+if\(typeof invalidateEvidenceReferences/);assert.match(interview,/\^Saved/);assert.match(interview,/evidenceReferencePanel\(\)/);assert.match(report,/evidenceReferencePanel\(\)/);assert.ok(index.indexOf('renderer/reference-matches.js')<index.indexOf('renderer/interview.js'));
});
test('late request errors cannot overwrite another patient or newer loaded matches',async()=>{
 const h=harness();let fail;h.ctx.hmr.api=()=>new Promise((resolve,reject)=>fail=reject);const pending=h.ctx.refreshEvidenceReferences();h.ctx.interviewId='other';fail(Error('old patient error'));await pending;assert.doesNotMatch(h.target.textContent,/old patient error/);
 h.ctx.hmr.api=async()=>response();await h.ctx.refreshEvidenceReferences();h.ctx.hmr.api=()=>new Promise((resolve,reject)=>fail=reject);const opening=h.click();h.ctx.invalidateEvidenceReferences('Newer state');fail(Error('old opening error'));await opening;assert.equal(h.target.textContent,'Newer state');
});
test('report uses report patient id, not last interview patient id',async()=>{
 const h=harness();h.ctx.page='report_editor';await h.ctx.refreshEvidenceReferences();assert.equal(h.calls[0][1],'/api/patients/2/reference-matches');
});
