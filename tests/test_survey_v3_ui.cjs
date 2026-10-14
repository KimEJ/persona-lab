'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const project=path.resolve(__dirname,'..'),html=fs.readFileSync(path.join(project,'web/index.html'),'utf8');
// The same small DOM substitute as test_result_filters.cjs and test_survey_v2_ui.cjs.
class Element {
 constructor(){this.hidden=false;this.disabled=false;this.innerHTML='';this.textContent='';this.value='';this.dataset={};this.parts=new Map();this.scrollTop=0;this.open=false;this.attributes={};this.classList={contains:()=>false,toggle(){}};}
 addEventListener(){}
 querySelector(selector){if(!this.parts.has(selector))this.parts.set(selector,new Element());return this.parts.get(selector);}
 querySelectorAll(){return [];}
 contains(){return false;}
 append(){}
 after(){}
 setAttribute(key,value){this.attributes[key]=value;}
 removeAttribute(key){delete this.attributes[key];}
 checkValidity(){return true;}
 close(){this.open=false;}
 focus(){}
 getBoundingClientRect(){return {width:400};}
}
const domains=['relevance','current_solution','clarity','benefit','differentiation','credibility','switching','usage','fair_price'];
const titles=['문제 관련성','현재 해결 수준','설명 명확성','개선 효익','차별성','주장 신뢰성','전환 부담','사용 의향','최대 지불 의향 가격대'];
const baseChoices=['relevant','sufficient','clear','better','distinct','supported','low','use','price_1'];
const questions=domains.map((domain,i)=>({id:domain,domain,title:titles[i],choices:[baseChoices[i],'unknown'],labels:{use:'있음',consider:'고려',not_use:'없음',unknown:'판단 불가'}}));
const acceptance={id:'price-acceptance-v1',domain:'acceptance',title:'가격 수용',derived:true,choices:['accept','reject','defer','uncertain','unknown','error','pending','not_run'],labels:{accept:'수용 가능',reject:'수용하지 않음',defer:'보류',uncertain:'상한 구간 내 판정 불가',unknown:'판단 불가',error:'오류',pending:'대기',not_run:'미실시'}};
const cell=choice=>({choice,reason:'',review:{marked:false,note:''},job_id:'job-'+choice});
const product={id:'item',name:'메모',price:{amount_minor:500,currency:'JPY',billing:'one_time'},valuation_unit:{currency:'JPY',billing:'one_time'},valuation_bands:[{low_minor:0,high_minor:999},{low_minor:1000,high_minor:1999},{low_minor:2000,high_minor:2999},{low_minor:3000,high_minor:null}]};
const item=(choice,usage='use')=>({...Object.fromEntries(domains.map((domain,i)=>[domain,cell(domain==='usage'?usage:baseChoices[i])])),product_id:'item',acceptance:{choice,derived:true,reason:'판매가격과 지불상한을 비교했습니다. <img>',input_job_ids:['job-use','job-price_1'],option_probabilities:null,probability_semantics:'not_provided'}});
const data={workflow:'product-survey-v3',repeat:0,repeats:1,count:4,questions:[...questions,acceptance],products:[product],people:['accept','reject','uncertain','not_run'].map((choice,i)=>({persona_id:String(i),name:'인물 '+i,age:30,age_group:'30–39세',sex:'여성',items:[item(choice)]})),usage_purchase:[{product_id:'item',paired_count:1,cells:[{usage:'use',purchase:'buy',count:1}]}]};
const resultContext=vm.createContext({Intl,window:{scrollY:0},document:{activeElement:null,createElement:()=>new Element()}});
vm.runInContext(fs.readFileSync(path.join(project,'web/results.js'),'utf8'),resultContext);
const resultRoot=new Element(),View=resultContext.window.ResponseResults,view=new View(resultRoot,{request:()=>{throw Error('Unexpected request');},onError:error=>{throw error;}});

async function resultChecks(workflow){
 const current=structuredClone(data);current.workflow=workflow;
 await view.load('new-run-'+workflow,current);
 assert.match(resultRoot.innerHTML,/최대 지불 가격대/);
 assert.doesNotMatch(resultRoot.innerHTML,/rr-offer|rr-context-summary|rr-current-product/);
 current.report_context={products:[{...current.products[0],document:'원문 <script>예제</script>',summary:'중복 상품 요약'}],panel:{selection:'random',sample_seed:17},selected_count:current.count,repeats:1,source:{name:'원천 자료',record_count:10000},model:{name:'내부 모델'},scenario_id:workflow};view.data=current;
 const completionContext=view.contextHTML();assert.match(completionContext,/상품·실험 조건|대상 인원|판매조건/);assert.doesNotMatch(completionContext,/중복 상품 요약|지불 가격대|질문 버전|가격대 탐색|가격대 설정|인물 자료|자료 인원|내부 모델|추출 기준|<dt>반복/);assert.doesNotMatch(completionContext,/<script>/);
 assert.match(resultRoot.innerHTML,/data-part="acceptance"/);
 assert.doesNotMatch(resultRoot.innerHTML,/최종 선택|적정가격|data-part="purchase"|data-part="cross"/);
 assert.equal(view.extraQuestions().length,7,'All base analysis questions remain');
 assert.equal((view.el('survey').innerHTML.match(/rr-survey-row/g)||[]).length,7);
 assert.match(view.el('acceptance').innerHTML,/data-filter="acceptance"/);
 assert.match(view.el('acceptance').innerHTML,/수용 가능/);
 assert.match(view.el('people').innerHTML,/가격 수용/);
 assert.doesNotMatch(view.el('people').innerHTML,/구매|최종 선택/);
 assert.equal(view.crossHTML(),'','No legacy usage-purchase cross table is exposed for WTP surveys');
 assert.equal((view.el('detail').innerHTML.match(/rr-assessment-head/g)||[]).length,10,'Nine model assessments and one calculated result');
 assert.equal((view.el('detail').innerHTML.match(/data-record=/g)||[]).length,9,'Calculated acceptance has no synthetic model record');
 assert.match(view.el('detail').innerHTML,/판매가격과 지불상한을 비교했습니다\. &lt;img&gt;/);
 assert.doesNotMatch(view.optionScores('acceptance',data.people[0].items[0].acceptance),/선택 점수/);
 const history={records:[{domain:'relevance',choice:'unknown',job_id:'private-logical-id',missing_information:['근거 <img>']} ]};
 assert.match(view.historyHTML(history),/선행 평가/);assert.match(view.historyHTML(history),/문제 관련성 · 판단 불가 · 근거 &lt;img&gt;/);assert.doesNotMatch(view.historyHTML(history),/private-logical-id|<img>/);assert.equal(view.historyHTML(null),'');
 view.data.people[0].items[0].acceptance.choice='error';view.renderDetail();assert.doesNotMatch(view.el('detail').innerHTML,/재시도: 가격 수용/,'Calculated results do not offer a separate model retry');view.data.people[0].items[0].acceptance.choice='accept';
 view.filters.acceptance='reject';assert.equal(view.filtered().length,1);assert.equal(view.filtered()[0].persona_id,'1');
 view.filters.acceptance=null;view.filters.mode='unknown';assert.equal(view.filtered().length,1,'A sale price inside the reported upper-limit band remains unconfirmed');
 view.filters.mode='not_run';assert.equal(view.filtered().length,1);view.filters.mode='all';
 const target={dataset:{filter:'acceptance',value:'reject'},hasAttribute:()=>false};await view.click({target:{closest:()=>target}});assert.equal(view.filters.acceptance,'reject');assert.equal(view.filtered().length,1);view.filters.acceptance=null;
 view.data.products.push({...structuredClone(product),id:'other',name:'다른 메모'});for(const person of view.data.people)person.items.push({...structuredClone(person.items[0]),product_id:'other'});
 view.data.price_points=[{name:'메모',domain:'acceptance',currency:'JPY',billing:'one_time',points:[{product_id:'item',amount_minor:500,share:.25,count:1,denominator:4}]}];view.render();
 assert.match(view.el('comparison').innerHTML,/가격 수용|가격별 수용/);assert.doesNotMatch(view.el('comparison').innerHTML,/가격별 선택|최종 선택|적정가격/);assert.match(view.el('detail').innerHTML,/rr-person-comparison/);
 // Stored legacy results keep their original meanings and purchase filters.
 const old=structuredClone(data);old.workflow='product-survey-v2';old.questions=[...questions.map(question=>question.domain==='fair_price'?{...question,title:'적정가격'}:question),{domain:'purchase',title:'최종 선택',choices:['buy','decline']}];for(const person of old.people)person.items[0].purchase=cell('buy');
 await view.load('old-run',old);assert.match(resultRoot.innerHTML,/최종 선택|적정가격/);assert.match(resultRoot.innerHTML,/data-part="purchase"/);assert.match(resultRoot.innerHTML,/data-part="cross"/);assert.equal(view.outcomeKind(),'purchase');
}

async function appChecks(workflow){
 const ids=new Map([...html.matchAll(/id="([^"]+)"/g)].map(match=>[match[1],new Element()]));
 const get=id=>{assert(ids.has(id),'Unexpected element '+id);return ids.get(id);};
 const state={history:[],deleted:[],model:{phase:'ready',info:{}},source:{},survey_questions:questions,prefectures:[]},requests=[],exports=[];
 let imported=null;
 const settings={title:'지불 가격대 평가',workflow,items:[{id:'item',name:'메모',document:'상품 문서',pricing:{state:'paid',amount:'500',currency:'JPY',billing:'one_time'},valuation:{mode:'manual',currency:'JPY',billing:'one_time',boundaries:['1000','2000','3000']}}],panel:{selection:'random',sample_size:2,sample_seed:17},settings:{repeats:1,seed:17}};
 const context=vm.createContext({console,structuredClone,URLSearchParams,Intl,Map,Number,String,Uint32Array,
  document:{documentElement:{lang:'ko'},body:{dataset:{token:'test'},classList:{contains:()=>false}},getElementById:get,addEventListener(){}},window:{webkit:{messageHandlers:{native:{postMessage:value=>exports.push(value)}}}},
  setTimeout:()=>1,clearTimeout(){},setInterval(){},crypto:{getRandomValues:array=>array},
  MarkdownEditor:{Editor:class{setHints(){}setMarkdown(markdown){this.markdown=markdown;}getMarkdown(){return this.markdown||'';}setEditable(){}captureHistory(){return {markdown:this.markdown};}restoreEditor(snapshot){this.markdown=snapshot.markdown;}}},
  ResponseResults:class{constructor(){this.repeat=0;}reset(){}setTagLocale(){}},
  fetch:async(route,request)=>{const body=request.body?JSON.parse(request.body):undefined;requests.push({route,body});let value;
   if(route==='/api/state')value=state;
   else if(route==='/api/experiments/import'){imported={...body.settings,id:'imported',revision:1,run:null,question_catalog:[...questions,acceptance]};value={id:imported.id};}
   else if(route==='/api/experiments/imported')value=imported;
   else if(route==='/api/panel')value={count:2,eligible_count:10};
   else if(route==='/api/panel/tags')value={tags:[],selected:[]};
   else throw Error('Unexpected route '+route);
   return {ok:true,json:async()=>structuredClone(value)};
  }});
 vm.runInContext(fs.readFileSync(path.join(project,'web/app.js'),'utf8'),context);const run=code=>vm.runInContext(code,context);
 await new Promise(resolve=>setImmediate(resolve));context.settings=settings;await run('importSettings(settings)');
 assert.equal(run('draft.workflow'),workflow);assert.equal(run('responseFlow()'),true);assert.equal(get('legacy-conditions').hidden,true);assert.equal(get('valuation-settings').hidden,false);assert.equal(get('valuation-heading').textContent,'최대 지불 가격대');assert.equal(get('export-settings').disabled,false);assert.equal(get('job-count').textContent,'18건','Derived acceptance is not counted as a tenth model question');
 assert.equal(run('surveyQuestions().length'),9);assert.equal(get('price-state').value,'paid');
 await run('exportSettings()');const exported=JSON.parse(exports.at(-1).body);assert.equal(exported.workflow,workflow);assert.deepEqual(exported.items,settings.items);assert.equal(exported.settings.seed,17);
 run("draft.items[0].valuation.boundaries=['1000','','3000'];renderValuations();renderNavigation();");assert.equal(get('primary-action').disabled,true);assert.match(get('valuation-error').textContent,/최대 지불 가격대/);
 run("draft.items[0].valuation.mode='auto';renderValuations();renderNavigation();");assert.equal(get('valuation-error').hidden,true);assert.equal(get('primary-action').disabled,false);
 for(const status of ['paused','interrupted']){
  context.runStatus=status;run("draft.run={status:runStatus,cursor:9,total:9,backend_errors:2,active:false};renderRun();");
  assert.equal(run('runRowsComplete()'),true);assert.equal(get('primary-action').dataset.action,workflow==='product-survey-v4'?'resume':'export','A full-row interrupted staged repair must remain resumable, while frozen V3 behavior is preserved');
  if(workflow==='product-survey-v4'){assert.equal(run('runComplete()'),false);assert.equal(get('primary-action').textContent,'이어 실행');assert.equal(get('primary-action').disabled,false);}
 }
 run("draft.run.status='completed_with_errors';renderRun();");assert.equal(run('runComplete()'),true);assert.equal(get('retry-run').hidden,false);assert.equal(get('retry-run').disabled,false);assert.equal(get('primary-action').dataset.action,'export');
 run("draft.workflow='product-survey-v2';renderValuations();");assert.equal(get('valuation-heading').textContent,'평가 가격대','Legacy settings retain the previous meaning');
}
(async()=>{for(const workflow of ['product-survey-v4','product-survey-v3']){await resultChecks(workflow);await appChecks(workflow);}})().then(()=>console.log('Survey V4/V3 UI passed: WTP and calculated acceptance, predecessor detail, preserved analysis, filters and comparison, legacy results, settings import/export and nine-question count.')).catch(error=>{console.error(error.stack);process.exitCode=1;});
