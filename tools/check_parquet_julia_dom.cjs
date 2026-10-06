// Tiny actual Parquet -> Julia -> UI/report check; jsdom is not a rendered browser.
const {JSDOM,VirtualConsole}=require('jsdom');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const root=path.resolve(__dirname,'..'),base='http://127.0.0.1:8787';
const original=JSON.parse(fs.readFileSync(path.join(root,'verification/parquet-original-import.json'),'utf8'));
const errors=[],virtual=new VirtualConsole();virtual.on('jsdomError',error=>errors.push(String(error)));
const dom=new JSDOM(fs.readFileSync(path.join(root,'web/index.html'),'utf8'),{url:base,runScripts:'outside-only',virtualConsole:virtual});
const {window}=dom,$=id=>window.document.getElementById(id);
window.fetch=(url,options)=>fetch(new URL(url,base),options);window.structuredClone=structuredClone;
window.HTMLElement.prototype.scrollIntoView=function(){};window.addEventListener('error',event=>errors.push(event.message));
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function until(predicate,label,timeout=90000){const end=Date.now()+timeout;while(Date.now()<end){if(predicate())return;await wait(50);}throw new Error(label+': '+$('error').textContent+' '+$('run-state').textContent);}
async function json(route,service=base){const response=await fetch(service+route);assert.equal(response.status,200);return response.json();}
function change(id,value){$(id).value=value;$(id).dispatchEvent(new window.Event('change',{bubbles:true}));}
async function main(){
 const source=(await json('/api/packs')).find(pack=>pack.id===original.pack_id);
 const page=await json('/api/personas?pack='+original.pack_id+'&offset=124980');assert.equal(page.matched_count,125000);
 const person=page.items.at(-1);assert.equal(Object.keys(person.raw).length,22);
 window.eval(fs.readFileSync(path.join(root,'web/app.js'),'utf8'));
 await until(()=>$('panel-count').textContent.includes('53명')&&!$('julia-option').disabled,'initial runtime');
 change('pack',original.pack_id);await until(()=>$('panel-count').textContent.includes('125,000명'),'original Parquet catalog');
 assert.ok($('source-info').textContent.includes('CC-BY-4.0'));
 $('query').value=person.uuid;$('filter-form').dispatchEvent(new window.Event('submit',{bubbles:true,cancelable:true}));
 await until(()=>$('panel-count').textContent.includes('1명'),'whole-panel UUID filter');assert.equal($('personas').children.length,1);
 $('personas').querySelector('button').click();const preview=JSON.parse($('persona-json').textContent);assert.deepEqual(preview.raw,person.raw);
 change('backend','julia');$('panel-budget').value='1500';change('event','repeated_crash');$('batch-size').value='32';
 $('a-name').value='メモ整理ツール A';$('b-name').value='メモ整理ツール B';
 const experiment='Parquet original one-person Julia connection';$('experiment-name').value=experiment;
 const before=(await json('/health','http://127.0.0.1:8082')).stats;const started=Date.now();
 $('start-run').click();await until(()=>$('run-state').textContent==='완료'&&$('result-description').textContent.includes(experiment)&&$('report-summary').textContent.includes('14/14'),'actual Julia and final report');
 const id=$('history').value,report=await json('/api/runs/'+id+'/report'),saved=await json('/api/runs/'+id+'/spec');
 const after=(await json('/health','http://127.0.0.1:8082')).stats;
 assert.equal(after.predict_requests-before.predict_requests,1);assert.equal(after.requested_rows-before.requested_rows,14);
 assert.equal(report.valid_decisions,14);assert.equal(report.backend_errors,0);assert.equal(report.backend_kind,'dedicated_local_decision');
 assert.equal(report.observed_personas,1);assert.equal(report.groups.length,14);
 for(const condition of ['A','B'])assert.equal(report.groups.filter(group=>group.product_id===condition).length,7);
 assert.equal(report.paired_transition_count,1);assert.equal(report.source.version,source.version);
 assert.equal(report.source.license_id,'CC-BY-4.0');assert.equal(report.assumptions.purchase_budget_jpy_minor,1500);
 assert.equal(report.scenario.events[0].code,'repeated_crash');
 const details=[];
 for(const record of report.examples.filter(row=>row.domain==='purchase')){
  const detail=await json('/api/runs/'+id+'/jobs/'+record.job_id);assert.deepEqual(detail.persona.raw,person.raw);
  assert.equal(detail.persona.content_hash,record.persona_content_hash);assert.equal(detail.source.version,report.source.version);
  assert.deepEqual(detail.product,saved.spec.products.find(product=>product.id===record.product_id));
  assert.deepEqual(detail.question,saved.spec.questions.find(question=>question.id===record.question_id));
  assert.deepEqual(detail.assumptions,saved.spec.assumptions);assert.deepEqual(detail.scenario,saved.spec.scenario);details.push(detail);
 }
 assert.equal(details.length,2);assert.equal(details[0].scenario.initial_state_id,details[1].scenario.initial_state_id);
 assert.ok($('comparison').textContent.includes('상품 A'));assert.ok($('comparison').textContent.includes('상품 B'));
 assert.ok($('transitions').textContent.includes('1쌍'));assert.ok($('report-summary').textContent.includes('실제 로컬 추론'));
 $('examples').querySelector('button').click();await until(()=>$('decision-json').textContent.includes('dedicated_local_decision'),'saved original condition UI');
 const shown=JSON.parse($('decision-json').textContent);assert.deepEqual(shown.persona.raw,person.raw);
 for(const format of ['json','csv','md']){
  const response=await fetch(new URL($('export-'+format).getAttribute('href'),base));assert.equal(response.status,200);
  const payload=await response.text();assert.ok(payload.includes('CC-BY-4.0'));assert.ok(payload.includes('NVIDIA'));assert.ok(payload.includes(report.source.version));
  fs.writeFileSync(path.join(root,'verification/parquet-one-person-julia-report.'+format),payload);
 }
 assert.equal(errors.length,0,errors.join('\n'));
 fs.writeFileSync(path.join(root,'verification/parquet-one-person-julia-details.json'),JSON.stringify({source:report.source,spec:saved.spec,details},null,2)+'\n');
 const receipt={verified_at:new Date().toISOString(),status:'passed',scope:'Actual one-person selection from imported125000 Parquet via DOM -> Julia batch -> original details -> paired A/B -> attributed exports; no rendered browser',checks:11,pack_id:original.pack_id,run_id:id,matched_personas:1,source_catalog_personas:125000,original_uuid:person.uuid,source_revision:report.source.upstream_revision,source_version:report.source.version,original_fields:22,planned_jobs:14,valid_decisions:report.valid_decisions,backend_errors:report.backend_errors,backend_kind:report.backend_kind,backend_id:report.backend_id,actual_julia_requests:after.predict_requests-before.predict_requests,actual_julia_requested_rows:after.requested_rows-before.requested_rows,groups:report.groups.length,paired_purchase_count:report.paired_transition_count,paired_purchase_transitions:report.paired_purchase_transitions,unknown_decisions:report.groups.reduce((total,group)=>total+group.unknown,0),budget_conflicts:report.consistency_warnings.purchase_above_explicit_budget,original_raw_and_conditions_verified:true,report_attribution_preserved:true,exports:['json','csv','md'],elapsed_seconds:(Date.now()-started)/1000,limits:['Tiny integration check; not behavioral accuracy or125000-person inference performance.','No visual/keyboard/browser E2E; IAB remains unavailable.']};
 fs.writeFileSync(path.join(root,'verification/parquet-julia-dom-api.json'),JSON.stringify(receipt,null,2)+'\n');process.stdout.write(JSON.stringify(receipt)+'\n');
}
main().catch(error=>{process.stderr.write(error.stack+'\n');process.exitCode=1;}).finally(()=>window.close());
