// Actual import controls + API; jsdom only, no OS browser or model experiment.
const {JSDOM,VirtualConsole}=require('jsdom');const assert=require('node:assert/strict');const fs=require('node:fs');const path=require('node:path');
const root=path.resolve(__dirname,'..'),base='http://127.0.0.1:8787';const id=process.argv[2];assert.match(id,/^[a-f0-9]{32}$/);
const errors=[];const virtual=new VirtualConsole();virtual.on('jsdomError',error=>errors.push(String(error)));
const dom=new JSDOM(fs.readFileSync(path.join(root,'web/index.html'),'utf8'),{url:base,runScripts:'outside-only',virtualConsole:virtual});const {window}=dom,$=id=>window.document.getElementById(id);
window.fetch=(url,options)=>fetch(new URL(url,base),options);window.structuredClone=structuredClone;window.HTMLElement.prototype.scrollIntoView=function(){};window.addEventListener('error',event=>errors.push(event.message));
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function until(predicate,label,timeout=120000){const limit=Date.now()+timeout;while(Date.now()<limit){if(predicate())return;if($('parquet-state').textContent.startsWith('실패'))throw new Error($('parquet-state').textContent);await wait(50);}throw new Error(label+': '+$('parquet-state').textContent+' '+$('error').textContent);}
async function json(route){return(await fetch(base+route)).json();}
async function main(){
 const initial=await json('/api/parquet-imports/'+id);assert.equal(initial.status,'paused');const started=Date.now();
 window.eval(fs.readFileSync(path.join(root,'web/app.js'),'utf8'));
 await until(()=>$('panel-count').textContent.includes('53명')&&[...$('parquet-history').options].some(option=>option.value===id),'initial catalog/config');
 assert.equal($('parquet-file').options.length,8);assert.equal($('parquet-start').disabled,false);
 $('parquet-import-panel').open=true;$('parquet-history').value=id;$('parquet-history').dispatchEvent(new window.Event('change',{bubbles:true}));
 await until(()=>$('parquet-state').textContent.startsWith('일시 중단')&&!$('parquet-resume').disabled,'saved import selected');
 $('parquet-resume').click();await until(()=>Number($('parquet-progress').value)>initial.rows&&!$('parquet-cancel').disabled,'actual conversion progress');
 $('parquet-cancel').click();await until(()=>$('parquet-state').textContent.startsWith('일시 중단')&&!$('parquet-resume').disabled,'UI cancel checkpoint');
 const paused=await json('/api/parquet-imports/'+id);assert.ok(paused.rows>initial.rows&&paused.rows<125000);assert.equal(paused.active,false);
 process.stdout.write(JSON.stringify({stage:'UI_cancel',rows:paused.rows})+'\n');
 $('parquet-resume').click();await until(()=>$('parquet-state').textContent.startsWith('완료')&&$('panel-count').textContent.includes('125,000명'),'publish+panel',180000);
 const completed=await json('/api/parquet-imports/'+id);assert.equal(completed.rows,125000);assert.equal($('pack').value,completed.pack_id);assert.equal($('personas').children.length,20);assert.ok($('source-info').textContent.includes('CC-BY-4.0'));
 const pack=(await json('/api/packs')).find(pack=>pack.id===completed.pack_id);assert.equal(pack.record_count,125000);assert.ok(pack.version.includes('f1f37019d8497143c507b3deb547e65646de2ab7'));
 const firstPage=await json('/api/personas?pack='+completed.pack_id);assert.equal(firstPage.matched_count,125000);assert.equal(Object.keys(firstPage.items[0].raw).length,22);
 $('next-page').click();await until(()=>$('page-info').textContent.startsWith('21'),'original shard pagination');
 $('query').value=firstPage.items[0].uuid;$('filter-form').dispatchEvent(new window.Event('submit',{bubbles:true,cancelable:true}));await until(()=>$('panel-count').textContent.includes('1명'),'whole shard UUID filter');assert.equal($('personas').children.length,1);
 $('personas').querySelector('button').click();assert.ok($('persona-json').textContent.includes('field_provenance'));
 assert.equal(errors.length,0,errors.join('\n'));
 const receipt={verified_at:new Date().toISOString(),status:'passed',scope:'DOM/API Parquet controls; no browser rendering and no model inference',checks:12,import_id:id,initial_rows:initial.rows,ui_paused_rows:paused.rows,completed_rows:completed.rows,pack_id:completed.pack_id,original_fields:22,whole_panel_filter_count:1,elapsed_seconds:(Date.now()-started)/1000};fs.writeFileSync(path.join(root,'verification/parquet-dom-api.json'),JSON.stringify(receipt,null,2)+'\n');process.stdout.write(JSON.stringify(receipt)+'\n');
}
main().catch(error=>{process.stderr.write(error.stack+'\n');process.exitCode=1;}).finally(()=>window.close());
