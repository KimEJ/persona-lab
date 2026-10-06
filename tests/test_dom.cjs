// DOM integration only: jsdom does not render or control an installed browser.
const {JSDOM,VirtualConsole}=require('jsdom');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const root=path.resolve(__dirname,'..');
const base=process.env.PERSONA_LAB_TEST_URL||'http://127.0.0.1:8787';
const errors=[];const console=new VirtualConsole();console.on('jsdomError',error=>errors.push(String(error)));
const dom=new JSDOM(fs.readFileSync(path.join(root,'web/index.html'),'utf8'),{url:base,runScripts:'outside-only',virtualConsole:console});
const {window}=dom;const $=id=>window.document.getElementById(id);
const requestPaths=[];window.fetch=(url,options)=>{if(options?.method==='POST')requestPaths.push(String(url));return fetch(new URL(url,base),options);};
window.structuredClone=structuredClone;
window.HTMLElement.prototype.scrollIntoView=function(){};
window.addEventListener('error',event=>errors.push(event.message));
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function until(condition,label){for(let i=0;i<200;i++){if(condition())return;await wait(25);}throw new Error('DOM wait failed: '+label+'; '+$('error').textContent);}
function change(id,value){$(id).value=value;$(id).dispatchEvent(new window.Event('change',{bubbles:true}));}
async function main(){
 window.eval(fs.readFileSync(path.join(root,'web/app.js'),'utf8'));
 const hasPublic=fs.existsSync(path.join(root,'data/packs/nemotron-japan-sample.jsonl'));
 await until(()=>$('panel-count').textContent.includes(hasPublic?'53명':'4명'),'initial installed panel');
 assert.equal($('personas').children.length,hasPublic?20:4);
 if(hasPublic){$('next-page').click();await until(()=>$('page-info').textContent.startsWith('21'),'pagination');}
 if($('pack').value!=='synthetic-fixture'){change('pack','synthetic-fixture');await until(()=>$('panel-count').textContent.includes('4명'),'fixture switch');}
 assert.equal($('fixture-budget').checked,true);
 $('personas').querySelector('button').click();assert.equal($('persona-detail').hidden,false);assert.ok($('persona-json').textContent.includes('field_provenance'));
 $('age-min').value='40';$('filter-form').dispatchEvent(new window.Event('submit',{bubbles:true,cancelable:true}));await until(()=>$('panel-count').textContent.includes('3명'),'filter');
 $('clear-filters').click();await until(()=>$('panel-count').textContent.includes('4명'),'reset');
 $('a-price').value='';$('start-run').click();await until(()=>!$('error').hidden,'empty input error');
 assert.equal($('history').value,'');$('a-price').value='2000';
 $('experiment-name').value='<img src=x onerror=alert(1)> DOM test';$('start-run').click();await until(()=>$('run-state').textContent==='완료','mock completion');
 await until(()=>$('report-content').hidden===false&&$('report-summary').textContent.includes('56/56'),'final comparison');
 assert.ok($('report-summary').textContent.includes('56/56'));
 assert.ok($('report-summary').textContent.includes('MOCK'));
 assert.ok($('transitions').textContent.includes('거절 → 구매'));
 assert.ok($('result-description').textContent.includes('<img src=x'));
 assert.equal(window.document.querySelectorAll('img').length,0);
 assert.ok($('examples').textContent.includes('fixture_budget_rule'));
 assert.ok($('export-csv').getAttribute('href').endsWith('format=csv'));
 assert.equal($('resume-run').disabled,true);
 $('examples').querySelector('button').click();await until(()=>!$('decision-detail').hidden,'saved original conditions');const detail=JSON.parse($('decision-json').textContent);assert.ok(detail.question.choices.includes('unknown'));assert.equal(detail.persona.content_hash,detail.saved_result.persona_content_hash);
 for(const id of['export-json','export-csv','export-md','export-spec']){const response=await fetch(new URL($(id).getAttribute('href'),base));assert.equal(response.status,200);assert.ok((await response.text()).length>10);}
 let julia=null,itemErrors=null;
 if(process.env.PERSONA_LAB_TEST_JULIA==='1'){
  assert.ok(hasPublic,'Prepare the optional public sample with python3 tools/prepare_public_sample.py before actual Julia tests.');
  assert.equal($('julia-option').disabled,false);
  change('pack','nemotron-japan-sample');await until(()=>$('panel-count').textContent.includes('53명'),'real source for Julia');
  $('query').value='09ae83ddc11745f6b995113fe7ed4a77';$('filter-form').dispatchEvent(new window.Event('submit',{bubbles:true,cancelable:true}));await until(()=>$('panel-count').textContent.includes('1명'),'one real persona');
  change('backend','julia');$('panel-budget').value='1500';change('event','repeated_crash');$('batch-size').value='32';$('experiment-name').value='Julia real DOM batch test';
  $('start-run').click();await until(()=>$('run-state').textContent==='완료'&&$('result-description').textContent.includes('Julia real DOM batch test')&&$('report-summary').textContent.includes('14/14'),'Julia completion');
  const response=await fetch(new URL('/api/runs/'+$('history').value+'/report',base));julia=await response.json();
  assert.equal(julia.valid_decisions,14);assert.equal(julia.backend_errors,0);assert.equal(julia.backend_kind,'dedicated_local_decision');
  assert.equal(julia.assumptions.purchase_budget_jpy_minor,1500);assert.equal(julia.scenario.events[0].code,'repeated_crash');
  assert.equal($('consistency-warning').hidden,julia.consistency_warnings.purchase_above_explicit_budget===0);
  assert.ok($('examples').textContent.includes('투입 입력 참조'));assert.ok($('report-summary').textContent.includes('실제 로컬 추론'));
  $('examples').querySelector('button').click();await until(()=>$('decision-json').textContent.includes('dedicated_local_decision'),'Julia original conditions');assert.equal(JSON.parse($('decision-json').textContent).question.choices.length,4);
  change('pack','synthetic-fixture');await until(()=>$('panel-count').textContent.includes('4명'),'item-error fixture');$('a-intro').value='<mask> explicit invalid input fixture';$('experiment-name').value='Julia per-item error DOM';
  $('start-run').click();await until(()=>$('run-state').textContent==='완료 · 오류 기록 있음'&&$('result-description').textContent.includes('Julia per-item error DOM')&&$('report-summary').textContent.includes('56/56'),'mixed item-error completion');
  const errorRun=$('history').value;const errorReport=await(await fetch(new URL('/api/runs/'+errorRun+'/report',base))).json();assert.equal(errorReport.backend_errors,28);assert.equal(errorReport.valid_decisions,28);assert.ok($('examples').textContent.includes('백엔드 오류'));assert.equal($('retry-run').disabled,false);
  const statsBefore=await(await fetch('http://127.0.0.1:8082/health')).json();$('retry-run').click();await until(()=>requestPaths.includes('/api/runs/'+errorRun+'/retry'),'retry button API');
  let retried=null;for(let i=0;i<100;i++){const status=await(await fetch(new URL('/api/runs/'+errorRun,base))).json();const health=await(await fetch('http://127.0.0.1:8082/health')).json();if(!status.active&&health.stats.predict_requests>statsBefore.stats.predict_requests){retried=status;break;}await wait(50);}
  assert.ok(retried);assert.equal(retried.cursor,56);assert.equal(retried.backend_errors,28);
  const afterRetry=await(await fetch(new URL('/api/runs/'+errorRun+'/report',base))).json();assert.deepEqual(afterRetry.examples.filter(row=>row.decision),errorReport.examples.filter(row=>row.decision));
  itemErrors={valid_decisions:errorReport.valid_decisions,backend_errors:errorReport.backend_errors,explicit_retry_sent:true,remaining_errors:retried.backend_errors,normal_examples_unchanged:true};
 }
 assert.equal(errors.length,0,errors.join('\n'));
 const receipt={verified_at:new Date().toISOString(),status:'passed',checks:julia?30:15,julia:julia?{valid_decisions:julia.valid_decisions,budget_conflicts:julia.consistency_warnings.purchase_above_explicit_budget}:null,item_error_case:itemErrors,scope:'DOM/API integration; no browser rendering or visual checks',run_id:$('history').value};fs.writeFileSync(path.join(root,'verification/dom-api.json'),JSON.stringify(receipt,null,2)+'\n');process.stdout.write(JSON.stringify(receipt)+'\n');
}
main().catch(error=>{process.stderr.write(error.stack+'\n');process.exitCode=1;}).finally(()=>window.close());
