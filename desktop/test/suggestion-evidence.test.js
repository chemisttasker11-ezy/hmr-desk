const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const helpers=require('../renderer/helpers');
const source=fs.readFileSync(require.resolve('../renderer/report-editor.js'),'utf8');
const hash='a'.repeat(64);
function setup(api){
 let changed=0;const node={innerHTML:''};
 const c=vm.createContext({H:{...helpers,autosaver:()=>({changed(){changed++;}})},esc:helpers.esc,
 page:'report_editor',hmr:{api},$:()=>node,errorText:e=>e.message,document:{addEventListener(){}}});
 vm.runInContext(source,c);c.renderReport=()=>{};
 vm.runInContext(`reportId='one';reportRecord={issues:[]};reportSuggestionSnapshot='${hash}';reportSuggestions=[{title:'Synthetic title',rec:'Review <original>',rationale:'Template reason',context_snapshot_sha256:'${hash}',evidence:[{id:'notes',kind:'notes',text:'Denies falls <not asserted>',source:'interview.json/notes',date:'',age_days:null,verification:'recorded text',flags:['Date not established']}]}]`,c);
 return {c,node,get changed(){return changed;},read:expr=>vm.runInContext(expr,c)};
}
test('exact source context required before explicit editable insertion, provenance retained',async()=>{
 const x=setup(async(method,path)=>{assert.equal(method,'GET');assert.equal(path,'/api/patients/one/suggestions/context');return {context_snapshot_sha256:hash};});
 const html=x.c.suggestionsHtml();assert.match(html,/Review &lt;original&gt;/);assert.match(html,/Denies falls &lt;not asserted&gt;/);
 assert.match(html,/not a patient finding/);assert.doesNotMatch(html,/<not asserted>/);
 await x.c.reportEditorClick({dataset:{suggestionAdd:'0'}});
 assert.equal(x.read('reportRecord.issues.length'),1);assert.equal(x.changed,1);
 assert.equal(x.read('reportRecord.issues[0].suggestion_source.context_snapshot_sha256'),hash);
 assert.equal(x.read('reportRecord.issues[0].suggestion_source.evidence[0].text'),'Denies falls <not asserted>');
 await x.c.reportEditorClick({dataset:{suggestionAdd:'0'}});assert.equal(x.read('reportRecord.issues.length'),1);
});
test('changed context blocks Add without modifying findings',async()=>{
 const x=setup(async()=>({context_snapshot_sha256:'b'.repeat(64)}));
 await x.c.reportEditorClick({dataset:{suggestionAdd:'0'}});
 assert.equal(x.read('reportRecord.issues.length'),0);assert.equal(x.changed,0);assert.match(x.node.innerHTML,/Source context changed/);
});
test('failed verification adds nothing and explains it',async()=>{
 const x=setup(async()=>{throw new Error('offline');});await x.c.reportEditorClick({dataset:{suggestionAdd:'0'}});
 assert.equal(x.read('reportRecord.issues.length'),0);assert.match(x.node.innerHTML,/Nothing added/);
});
for(const mode of ['patient','record','reload'])test('late Add verification ignored after '+mode+' change',async()=>{
 let finish;const x=setup(()=>new Promise(r=>finish=r));const pending=x.c.reportEditorClick({dataset:{suggestionAdd:'0'}});
 if(mode==='patient')vm.runInContext("reportId='other'",x.c);
 if(mode==='record')vm.runInContext('reportRecord={issues:[]}',x.c);
 if(mode==='reload')vm.runInContext('reportSuggestions=[];reportSuggestionSnapshot=""',x.c);
 finish({context_snapshot_sha256:hash});await pending;
 assert.equal(x.read('reportRecord.issues.length'),0);assert.equal(x.changed,0);
});
test('latest reload wins over old async response',async()=>{
 const requests=[];const x=setup(()=>new Promise(r=>requests.push(r)));
 const first=x.c.loadSuggestions(),second=x.c.loadSuggestions();
 requests[1]({suggestions:[{title:'New'}],context_gaps:[],context_snapshot_sha256:hash});await second;
 requests[0]({suggestions:[{title:'Old'}],context_gaps:[],context_snapshot_sha256:'b'.repeat(64)});await first;
 assert.equal(x.read('reportSuggestions[0].title'),'New');assert.equal(x.read('reportSuggestionSnapshot'),hash);
});
