'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');

class Element {
 constructor(){this.hidden=false;this.innerHTML='';this.textContent='';this.value='';this.dataset={};this.parts=new Map();this.scrollTop=0;this.open=false;}
 addEventListener(){}
 querySelector(selector){if(!this.parts.has(selector))this.parts.set(selector,new Element());return this.parts.get(selector);}
 querySelectorAll(){return [];}
 contains(){return false;}
 append(){}
 after(){}
}
const context=vm.createContext({Intl,window:{scrollY:0},document:{activeElement:null,createElement:()=>new Element()}});
vm.runInContext(fs.readFileSync(path.resolve(__dirname,'../web/results.js'),'utf8'),context);
const root=new Element(),View=context.window.ResponseResults;
const view=new View(root,{request:()=>{throw Error('Unexpected request');},onError:error=>{throw error;}});
const cell=choice=>({choice}),item=(id,usage='use')=>({product_id:id,usage:cell(usage),fair_price:cell('not_run'),purchase:cell('buy')});
const person=(id,usages)=>({persona_id:id,name:'인물 '+id,age:30,age_group:'30–39세',sex:'여성',items:usages.map((usage,i)=>item('product-'+i,usage))});
const multi={repeat:0,repeats:1,count:3,products:[{id:'product-0',name:'기본'},{id:'product-1',name:'비교'}],people:[person('changed',['use','not_use']),person('same',['use','use']),person('unknown',['unknown','unknown'])]};

async function main(){
 await view.load('experiment',structuredClone(multi));
 assert.match(root.innerHTML,/<option value="changed">달라진 판단<\/option>/);
 view.filters.mode='changed';view.render();
 assert.equal(view.filtered().length,1,'Comparisons keep the changed-judgment filter');
 assert.equal(view.filtered()[0].persona_id,'changed');

 const single=structuredClone(multi);single.products=single.products.slice(0,1);for(const person of single.people)person.items=person.items.slice(0,1);
 view.page=3;await view.load('experiment',single);
 assert.equal(view.filters.mode,'all','Refreshing a comparison with one product clears the stale filter');
 assert.equal(view.page,0);
 assert.equal(root.querySelector('[data-mode]').value,'all');
 assert.doesNotMatch(root.innerHTML,/<option value="changed">/);
 assert.equal(view.filtered().length,3);
 assert.equal(view.el('selection').textContent,'전체 · 3명');

 view.filters.mode='changed';view.filters.query='same';view.page=2;view.render();
 assert.equal(view.filters.mode,'all','Rendering also recovers a stale comparison mode');
 assert.equal(view.filters.query,'same','Independent filters remain selected');
 assert.equal(view.filtered().length,1);
 view.filters.query='';view.filters.mode='changed';
 assert.equal(view.filtered().length,3,'Direct list refresh cannot leave a single product empty');
 assert.equal(view.filters.mode,'all');
 view.filters.mode='unknown';view.render();
 assert.equal(view.filters.mode,'unknown','Other response modes remain available');
 assert.equal(view.filtered().length,1);

 await view.load('experiment',structuredClone(multi));view.filters.mode='changed';view.render();
 assert.match(root.innerHTML,/<option value="changed">달라진 판단<\/option>/);
 assert.equal(view.filtered().length,1,'The comparison filter is restored for multiple products');
 view.data.report_context={panel:{tags:['skill:문서 정리','interest:<script>'],query:'기존 검색'}};
 let conditions=view.contextHTML();
 assert.match(conditions,/#문서 정리 · #&lt;script&gt; · 하나 이상/);
 assert.match(conditions,/대상 태그/);
 assert.match(conditions,/검색: 기존 검색/);
 assert.doesNotMatch(conditions,/skill:|interest:|<script>/);
 view.data.report_context.panel.tag_mode='all';conditions=view.contextHTML();
 assert.match(conditions,/#문서 정리 · #&lt;script&gt; · 모두/);
 const translated='skill:concept/document-organization',legacy='interest:読書';
 view.data.report_context={panel:{tags:[translated,legacy],tag_mode:'all'},tag_labels:{
  [translated]:{ko:'문서 정리',en:'Document organization',ja:'文書整理'},
  [legacy]:{ko:'독서 <태그>',en:'Reading <tag>',ja:'読書 <タグ>'},
 }};
 const before=JSON.stringify(view.data.report_context.panel);
 assert.equal(view.tagLocale,'ko');view.render();
 assert.match(root.innerHTML,/#문서 정리 · #독서 &lt;태그&gt; · 모두/);
 view.setTagLocale('en');assert.match(root.innerHTML,/#Document organization · #Reading &lt;tag&gt; · 모두/);
 view.setTagLocale('ja');assert.match(root.innerHTML,/#文書整理 · #読書 &lt;タグ&gt; · 모두/);
 assert.equal(JSON.stringify(view.data.report_context.panel),before,'Locale changes never rewrite stored cohort conditions');
 assert.equal(view.filters.mode,'changed','Locale rerenders retain result filters');
 view.reset();assert.equal(view.tagLocale,'ja','Display preference survives experiment changes');
 console.log('Result filters passed: comparison filters, tag conditions, escaped Korean/English/Japanese labels, and unchanged cohort settings.');
}
main().catch(error=>{console.error(error.stack);process.exitCode=1;});
