'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const root=path.resolve(__dirname,'..'),html=fs.readFileSync(path.join(root,'web/index.html'),'utf8');
assert(!/data-step=|panel-preview|panel-person/.test(html));
assert(!/id="workbench-tabs"|data-view=|id="partial-results"/.test(html),'Setup and results share one experiment screen');
assert.match(html,/id="experiment-setup"/);
assert.match(html,/id="panel-sample-size"[^>]*value="100"/);
const ids=new Map();
class Element {
 constructor(){this.hidden=false;this.disabled=false;this.value='';this.textContent='';this.innerHTML='';this.dataset={};this.listeners={};this.valid=true;this.attributes={};this.classList={contains:()=>false,toggle:()=>{}};}
 addEventListener(type,handler){(this.listeners[type]??=[]).push(handler);}
 querySelectorAll(){return [];}
 querySelector(){return new Element();}
 setAttribute(key,value){this.attributes[key]=value;}
 removeAttribute(key){delete this.attributes[key];}
 checkValidity(){return this.valid;}
 close(){this.open=false;}
 focus(){}
 contains(){return false;}
 closest(){return null;}
 async dispatch(type){const event={target:this,preventDefault(){}};for(let element=this;element;element=element.parent)for(const handler of element.listeners[type]||[])await handler(event);}
}
for(const match of html.matchAll(/id="([^"]+)"/g))ids.set(match[1],new Element());
const $=id=>{assert(ids.has(id),'Unexpected element '+id);return ids.get(id);};
const domains=['need','understanding','usage','alternatives','trust','onboarding','fair_price','purchase'];
const options=[['now','later','none','unknown'],['clear','confused','unknown'],['use','not_use','unknown'],['offered_product','current_method','do_nothing','unknown'],['accept','request_evidence','reject','unknown'],['proceed','seek_help','stop','unknown'],['price_0','price_1','price_2','price_3','unknown'],['buy','defer','decline','unknown']];
const titles=['필요성','상품 이해','사용 의향','대안 비교','신뢰','도입','적정가격','최종 선택'];
const questions=domains.map((domain,i)=>({id:domain,domain,title:titles[i],prompt:titles[i]+'을 선택하세요.',choices:options[i],labels:Object.fromEntries(options[i].map(code=>[code,code==='unknown'?'판단 불가':code==='accept'?'수용':code]))}));
const appState={model:{phase:'ready'},history:[],deleted:[],prefectures:[],survey_questions:questions};
let savedDraft=null,sampleSeed=200,requests=[],deferredPanels=null;
const ctx=vm.createContext({console,structuredClone,URLSearchParams,Intl,Map,Number,String,Uint32Array,
 document:{body:{dataset:{token:'test'},classList:{contains:()=>false}},getElementById:$,querySelectorAll:()=>[],addEventListener(){}},window:{},
 crypto:{getRandomValues:array=>{array[0]=sampleSeed++;return array;}},setTimeout:()=>1,clearTimeout(){},setInterval(){},
 MarkdownEditor:{Editor:class{constructor(){this.markdown='';}setHints(){}setMarkdown(markdown){this.markdown=markdown;}getMarkdown(){return this.markdown;}setEditable(){}captureHistory(){return {markdown:this.markdown};}restoreEditor(snapshot){this.markdown=snapshot.markdown;}}},
 ResponseResults:class{constructor(){this.repeat=0;}reset(){this.repeat=0;}setTagLocale(locale){this.tagLocale=locale;}async load(id,data){this.data=data;}},
 fetch:async(route,request)=>{
  const body=request?.body?JSON.parse(request.body):undefined;requests.push({route,body});let data;
  if(route==='/api/state')data=appState;
  else if(route==='/api/panel/tags')data={tags:[{id:'interest:読書',label:'読書',kind:'interest',count:9}],matched:9,total:175};
  else if(route==='/api/panel'){
   if(deferredPanels)data=await new Promise(resolve=>deferredPanels.push(resolve));
   else data={count:Math.min(body.panel.sample_size||100,175),eligible_count:175,requested_size:body.panel.sample_size||100,items:[]};
  }else if(route.endsWith('/save'))data=savedDraft={...body,revision:(body.revision||0)+1};
  else if(route.endsWith('/start'))data=savedDraft={...savedDraft,run:{active:true,total:800,cursor:0,status:'running',backend_errors:0}};
  else if(route==='/api/experiments/test')data=savedDraft;
  else if(route.includes('/report?repeat='))data={completed_jobs:10,planned_jobs:10,backend_errors:0,backend_kind:'clef',responses:{count:1,repeat:Number(route.split('=')[1])}};
  else if(route.endsWith('/export'))data={body:'<html>보고서</html>',filename:'report.html',mime:'text/html'};
  else throw Error('Unexpected request '+route);
  return {ok:true,json:async()=>structuredClone(data)};
 }});
vm.runInContext(fs.readFileSync(path.join(root,'web/app.js'),'utf8'),ctx);
const exec=code=>vm.runInContext(code,ctx),tick=()=>new Promise(resolve=>setImmediate(resolve));
async function appChecks(){
 await tick();assert.equal($('empty-view').hidden,false);assert.equal(requests.filter(r=>r.route==='/api/panel').length,0);
 savedDraft={id:'test',revision:1,title:'새 실험',workflow:'product-survey-v1',items:[{id:'item',name:'메모',document:'문서',pricing:{state:'free',amount:'',currency:'JPY',billing:'one_time'}}],panel:{selection:'random',sample_size:100,sample_seed:123},settings:{repeats:1,seed:42},run:null};
 ctx.testDraft=structuredClone(savedDraft);
 exec("draft=testDraft;itemId='item';state="+JSON.stringify(appState)+";editor.setMarkdown('문서');fillItemFields();fillConditions();setView('experiment');renderRun();");await exec('refreshPanel();');
 assert.equal($('primary-action').textContent,'실험 시작');assert.equal($('previous-step').hidden,true);assert.equal($('input-view').hidden,false);assert.equal($('run-view').hidden,false);assert.equal($('experiment-setup').hidden,false);assert.equal($('results-view').hidden,true);assert.equal($('panel-sample-size').value,100);assert(!html.includes('id="survey-outline"'),'Question descriptions stay in reports');
 for(const field of ['name','document']){exec("draft.items[0]."+field+"=' ';editor.setMarkdown(draft.items[0].document);dirty=true;");await $('primary-action').dispatch('click');assert.equal(exec('view'),'experiment','Empty '+field+' must stay in the experiment');assert.equal(requests.filter(r=>r.route.endsWith('/start')).length,0);exec("draft.items[0]."+field+"="+JSON.stringify(savedDraft.items[0][field])+";");if(field==='name')exec("draft.items[0].name='메모';");else exec("draft.items[0].document='문서';editor.setMarkdown('문서');");}
 exec("itemInputError=new Error('가격 오류');");await $('primary-action').dispatch('click');assert.equal(exec('view'),'experiment');assert.equal($('error').textContent,'가격 오류');
 exec("itemInputError=null;dirty=true;");assert.equal($('primary-action').textContent,'실험 시작');assert.equal($('previous-step').hidden,true);assert.equal($('job-count').textContent,'800건');assert.equal($('panel-count').textContent,'100명');
 const panel=requests.findLast(r=>r.route==='/api/panel');assert.equal(panel.body.experiment_id,'test');assert.equal(panel.body.panel.sample_seed,123);assert.equal(panel.body.panel.selection,'random');assert(requests.some(r=>r.route.endsWith('/save')));
 // Native input values are strings. Sampling seed is independent of the repeat seed.
 for(const id of ['panel-prefecture','panel-age-min','panel-age-max','panel-sex'])$(id).value='';$('panel-sample-size').value='100';$('repeats').value='1';$('seed').value='42';
 await $('resample-panel').dispatch('click');assert.equal(exec('draft.panel.sample_seed'),200);assert.equal(exec('draft.settings.seed'),42);assert.equal(exec('draft.panel.sample_size'),100);
 $('panel-sample-size').value='150';await $('panel-sample-size').dispatch('input');await exec('refreshPanel()');assert.equal($('panel-count').textContent,'150명');assert.equal($('job-count').textContent,'1,200건');
 // Replies for old filters cannot overwrite the latest draw count.
 deferredPanels=[];const first=exec('refreshPanel()'),second=exec('refreshPanel()');await tick();assert.equal(deferredPanels.length,2);deferredPanels[1]({count:20,eligible_count:20});await second;deferredPanels[0]({count:10,eligible_count:10});await first;assert.equal($('panel-count').textContent,'20명');deferredPanels=null;
 $('panel-sample-size').valid=false;await $('panel-sample-size').dispatch('input');assert.equal($('primary-action').disabled,true);$('panel-sample-size').valid=true;await $('panel-sample-size').dispatch('input');await exec('refreshPanel()');
 await $('primary-action').dispatch('click');assert.equal(requests.filter(r=>r.route.endsWith('/start')).length,1,'The experiment starts with one click');assert.equal(exec('view'),'experiment');assert.equal($('primary-action').textContent,'실행 중');assert.equal($('primary-action').disabled,true);assert.equal($('resample-panel').disabled,true);
 assert.equal($('experiment-setup').hidden,true);assert.equal($('results-view').hidden,false);assert.equal($('results-content').hidden,true);assert.equal($('results-empty').hidden,false);
 savedDraft={...savedDraft,run:{active:false,total:800,cursor:800,status:'completed',backend_errors:0}};await exec("selectExperiment('test')");assert.equal(exec('view'),'experiment');assert.equal($('experiment-setup').hidden,true);assert.equal($('results-view').hidden,false);assert.equal($('results-content').hidden,false);assert.equal($('primary-action').textContent,'보고서 저장');assert.equal($('primary-action').dataset.action,'export');
 exec("window.webkit={messageHandlers:{native:{postMessage(){}}}};");await $('primary-action').dispatch('click');assert(requests.some(request=>request.route.endsWith('/export')),'Completed runs export directly without a results navigation action');
 savedDraft={...savedDraft,run:{active:false,total:800,cursor:8,status:'paused',backend_errors:0}};await exec("selectExperiment('test')");assert.equal(exec('view'),'experiment');assert.equal($('primary-action').textContent,'이어 실행');assert.equal($('experiment-setup').hidden,true);assert.equal($('results-view').hidden,false);assert.equal($('results-content').hidden,false);assert.equal($('resample-panel').disabled,true);

}
function resultChecks(){
 const results=vm.createContext({window:{},Intl,Map,Number,String});vm.runInContext(fs.readFileSync(path.join(root,'web/results.js'),'utf8'),results);const View=results.window.ResponseResults,view=Object.create(View.prototype),parts={};
 const cell=choice=>({choice,reason:'',missing_information:[],review:{marked:false,note:''},job_id:'job-'+choice,evidence:[],option_probabilities:null});
 const item=(overrides={})=>Object.assign({product_id:'item'},Object.fromEntries(domains.map((kind,i)=>[kind,cell(options[i][0])])),overrides);
 view.data={questions,products:[{id:'item',name:'메모',price:{amount_minor:0,currency:'JPY',billing:'one_time'},valuation_unit:{currency:'JPY',billing:'one_time'},valuation_bands:[{low_minor:0,high_minor:999},{low_minor:1000,high_minor:1999},{low_minor:2000,high_minor:2999},{low_minor:3000,high_minor:null}]}],count:2,people:[{persona_id:'1',uuid:'1',name:'가',age:25,age_group:'18–29세',sex:'여성',items:[item()]},{persona_id:'2',uuid:'2',name:'나',age:45,age_group:'40–49세',sex:'남성',items:[item({trust:cell('unknown'),need:cell('none')})]}]};
 view.productId='item';view.personId='1';view.filters={mode:'all',query:''};view.el=name=>parts[name]??=(new Element());view.render=()=>{};
 assert.equal(view.extraQuestions().length,5);view.renderSurvey();assert.equal((parts.survey.innerHTML.match(/class="rr-survey-row"/g)||[]).length,5);assert.match(parts.survey.innerHTML,/data-filter="trust"/);assert.match(parts.survey.innerHTML,/50\.0%/);assert.equal(view.label('purchase','buy'),'사용');
 view.filters.trust='unknown';assert.equal(view.filtered().length,1);assert.equal(view.filtered()[0].persona_id,'2');view.filters.trust=null;view.filters.mode='unknown';assert.equal(view.filtered().length,1);view.filters.mode='all';view.data.people[1].items[0].onboarding=cell('error');view.filters.mode='errors';assert.equal(view.filtered().length,1);view.filters.mode='all';
 view.renderDetail();assert.equal((parts.detail.innerHTML.match(/class="rr-assessment-head"/g)||[]).length,8);assert(parts.detail.innerHTML.indexOf('최종 선택')<parts.detail.innerHTML.indexOf('필요성'));assert.equal((parts.detail.innerHTML.match(/data-record=/g)||[]).length,8);
 view.data.people[0].items[0].need.reason='<img src=x onerror=bad()> 원문';view.renderDetail();assert(!parts.detail.innerHTML.includes('<img'));assert(parts.detail.innerHTML.includes('&lt;img'));
 delete view.data.questions;assert.equal(view.questions().length,3);view.renderDetail();assert.equal((parts.detail.innerHTML.match(/class="rr-assessment-head"/g)||[]).length,3);assert.equal(view.filtered().length,2);
}
appChecks().then(()=>{resultChecks();console.log('Survey UI passed: single setup/live-results screen, automatic report display, direct export, guarded start, frozen/history/resume states, adjustable seeded random sample, stale reply rejection, eight details, five extra distributions, all-stage filters, escaping and legacy rendering.');}).catch(error=>{console.error(error.stack);process.exitCode=1;});
