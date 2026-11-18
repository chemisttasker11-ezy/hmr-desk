const test=require('node:test');const assert=require('node:assert/strict');
const fs=require('node:fs');const path=require('node:path');const vm=require('node:vm');const crypto=require('node:crypto');
const main=fs.readFileSync(path.join(__dirname,'..','main.js'),'utf8');
const text=main.slice(main.indexOf("ipcMain.handle('local-reference-pick'"),main.indexOf("ipcMain.handle('open-report-version'"));
function harness(){
  const callbacks={};const data=Buffer.from('%PDF-synthetic-test-only');const hash=crypto.createHash('sha256').update(data).digest('hex');const win={webContents:{}};const loaded=[];const calls=[];
  const context={ipcMain:{handle:(name,fn)=>callbacks[name]=fn},win,dialog:{},api:async(...args)=>{calls.push(args);return {path:'/synthetic/reference.pdf',page:2,pdf_sha256:hash}},fsp:{lstat:async()=>({isFile:()=>true,isSymbolicLink:()=>false,size:data.length}),readFile:async()=>data},require,pdfViewerWindow:null,BrowserWindow:class{constructor(options){this.webContents={setWindowOpenHandler:()=>{},on:()=>{}};this.options=options;}loadURL(url){loaded.push(url)}isDestroyed(){return false}close(){}}};
  vm.runInNewContext(text,context);return {callbacks,context,hash,win,loaded,calls};
}
test('original opening binds exact current hash and physical page and uses sandboxed viewer',async()=>{
 const h=harness();await h.callbacks['local-reference-open']({sender:h.win.webContents},h.hash,2);
 assert.match(h.loaded[0],/reference\.pdf#page=2$/);assert.equal(h.calls[0][2].pdf_sha256,h.hash);assert.equal(h.calls[0][2].page,2);
 assert.equal(h.context.pdfViewerWindow.options.webPreferences.sandbox,true);assert.equal(h.context.pdfViewerWindow.options.webPreferences.nodeIntegration,false);
});
test('original opening refuses renderer paths, other senders, unsafe pages, and modified files',async()=>{
 const h=harness();const open=h.callbacks['local-reference-open'];
 for(const args of [[{sender:{}},h.hash,2],[{sender:h.win.webContents},'/synthetic.pdf',2],[{sender:h.win.webContents},h.hash,1.5]])await assert.rejects(open(...args));
 h.context.fsp.readFile=async()=>Buffer.from('changed');await assert.rejects(open({sender:h.win.webContents},h.hash,2),/changed/);assert.equal(h.loaded.length,0);
});
test('reference UI labels physical page, edition and review, escapes source, has no insert control',()=>{
 const source=fs.readFileSync(path.join(__dirname,'..','renderer','report-editor.js'),'utf8');
 const fn=source.slice(source.indexOf('function localReferenceHtml'),source.indexOf("document.addEventListener('click', async event",source.indexOf('function localReferenceHtml')));
 const ctx={esc:require('../renderer/helpers').esc};vm.runInNewContext(fn,ctx);
 const html=ctx.localReferenceHtml({reference:{edition:'synthetic <edition>',page_count:3,pdf_sha256:'a'.repeat(64)},results:[{title:'synthetic <script>',edition:'test',page:2,section_page:1,section_page_end:2,snippet:'exact <quoted> text'}]});
 assert.match(html,/Physical PDF page 2/);assert.match(html,/Section pages 1-2/);assert.match(html,/Pharmacist review required/);assert.match(html,/&lt;script&gt;/);assert.doesNotMatch(html,/<script>/);assert.doesNotMatch(html,/Insert|data-library-insert/);
});
