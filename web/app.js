'use strict';
const $=id=>document.getElementById(id);
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const domains={need:'필요',understanding:'이해',alternatives:'대안',purchase:'구매',trust:'신뢰',onboarding:'온보딩',churn:'조건부 이탈'};
const choices={now:'지금 필요',later:'나중에',none:'필요 없음',unknown:'판단 불가',clear:'이해',confused:'혼란',offered_product:'제시 상품',current_method:'현재 방식',do_nothing:'아무것도 안 함',buy:'구매',defer:'보류',decline:'거절',accept:'수용',request_evidence:'근거 요청',reject:'거부',proceed:'진행',seek_help:'도움 요청',stop:'중단',stay:'유지',reduce:'사용 축소',leave:'이탈 고려'};
const states={preparing:'패널 검사 중',ready:'준비됨',running:'실행 중',retrying:'오류 재시도 중',completed_with_errors:'완료 · 오류 기록 있음',paused:'일시 중단',interrupted:'이전 실행이 중단됨',completed:'완료',failed:'실패 · 원인 확인 필요'};
let packs=[],defaults=null,panel=null,offset=0,currentRun=null,pollBusy=false,lastCursor=-1,lastStatus='',previewItems=[];

async function api(path,body){
 const options=body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-Persona-Lab':'demo-v1'},body:JSON.stringify(body)};
 const response=await fetch(path,options),data=await response.json();
 if(!response.ok)throw new Error(data.error||`요청 실패 (${response.status})`);return data;
}
function showError(error){$('error').textContent=String(error.message||error);$('error').hidden=false;$('error').scrollIntoView({block:'nearest'});}
function clearError(){$('error').hidden=true;}
function activePack(){return packs.find(p=>p.id===$('pack').value);}
function filterParams(){const p={selection:'filter'};for(const [id,key]of[['prefecture','prefecture'],['query','query'],['age-min','age_min'],['age-max','age_max']]){const v=$(id).value.trim();if(v!=='')p[key]=key.startsWith('age_')?Number(v):v;}return Object.keys(p).length===1?{selection:'all'}:p;}
function updateEstimate(){const n=panel?.matched_count||0;const repeats=Number($('repeats').value);$('job-estimate').textContent=`${n.toLocaleString()}명 × 2안 × 7영역 × ${Number.isFinite(repeats)?repeats:0}회`;}
async function loadPanel(){
 clearError();const params=new URLSearchParams({pack:$('pack').value,offset:String(offset)});
 for(const[k,v]of Object.entries(filterParams()))if(k!=='selection')params.set(k,String(v));
 panel=await api('/api/personas?'+params);previewItems=panel.items;
 $('panel-count').textContent=`이번 패널 ${panel.matched_count.toLocaleString()}명`;
 $('personas').innerHTML=panel.items.length?panel.items.map((p,i)=>`<tr><td class="uuid" title="${esc(p.uuid)}">${esc(p.uuid.slice(0,12))}…</td><td>${esc(p.raw.age??'미제공')}</td><td>${esc(p.raw.prefecture??'미제공')}</td><td>${esc(p.raw.occupation??'미제공')}</td><td>${Object.keys(p.missing).length}개</td><td><button class="quiet" data-persona="${i}">보기</button></td></tr>`).join(''):'<tr><td colspan="6">필터에 맞는 인물이 없습니다. 조건을 넓혀 주세요.</td></tr>';
 $('page-info').textContent=panel.matched_count?`${offset+1}–${Math.min(offset+20,panel.matched_count)} / ${panel.matched_count}명 · 20행은 화면 페이지 크기입니다.`:'0명';
 $('prev-page').disabled=offset===0;$('next-page').disabled=offset+20>=panel.matched_count;
 $('start-run').disabled=panel.matched_count===0||Boolean(currentRun&&$('cancel-run').disabled===false);
 updateEstimate();
}
async function selectPack(){
 offset=0;const p=activePack();
 $('source-info').innerHTML=`<span>${esc(p.origin==='project_synthetic_fixture'?'자체 합성 fixture · NVIDIA 데이터 아님':p.source_id==='nvidia/Nemotron-Personas-Japan'?'NVIDIA 합성 소스 · 원본 출처 확인':'명시적 외부 합성 소스 · 제공된 출처 metadata')}</span><span>설치 ${p.record_count.toLocaleString()}명${p.upstream_record_count?` / 원본 ${p.upstream_record_count.toLocaleString()}행`:''}</span><span><a href="${esc(p.url.startsWith('https:')?p.url:'#panel')}" target="_blank" rel="noreferrer">출처</a> · <a href="${esc(p.license_url.startsWith('https:')?p.license_url:'#panel')}" target="_blank" rel="noreferrer">${esc(p.license_id)}</a></span><span>여섯 관점 = UUID 하나의 인물</span>`;
 $('fixture-budget').disabled=p.source_id!=='persona-lab/synthetic-fixture';$('fixture-budget').checked=p.source_id==='persona-lab/synthetic-fixture';
 for(const id of['age-min','age-max','query'])$(id).value='';
 $('prefecture').innerHTML='<option value="">전체</option>';
 // All 47 Japanese prefectures are static names, not fetched panel records.
 const prefectures=['北海道','青森県','岩手県','宮城県','秋田県','山形県','福島県','茨城県','栃木県','群馬県','埼玉県','千葉県','東京都','神奈川県','新潟県','富山県','石川県','福井県','山梨県','長野県','岐阜県','静岡県','愛知県','三重県','滋賀県','京都府','大阪府','兵庫県','奈良県','和歌山県','鳥取県','島根県','岡山県','広島県','山口県','徳島県','香川県','愛媛県','高知県','福岡県','佐賀県','長崎県','熊本県','大分県','宮崎県','鹿児島県','沖縄県'];
 $('prefecture').innerHTML+=prefectures.map(region=>`<option>${esc(region)}</option>`).join('');
 $('persona-detail').hidden=true;await loadPanel();explainBackend();
}
function fillProduct(prefix,product){for(const field of['name','intro'])$(prefix+'-'+field).value=product[field];$(prefix+'-features').value=product.features.join('\n');for(const[field,key]of[['price','amount_minor'],['currency','currency'],['billing','billing']])$(prefix+'-'+field).value=product.price[key];}
function product(prefix,id){return{id,name:$(prefix+'-name').value.trim(),intro:$(prefix+'-intro').value.trim(),features:$(prefix+'-features').value.split('\n').map(f=>f.trim()).filter(Boolean),price:{amount_minor:Number($(prefix+'-price').value),currency:$(prefix+'-currency').value,billing:$(prefix+'-billing').value}};}
function buildSpec(){
 for(const id of['experiment-name','a-name','a-price','a-intro','b-name','b-price','b-intro','batch-size','repeats','seed']){const el=$(id);if(el.value.trim()===''||!el.checkValidity()){el.reportValidity();el.focus();throw new Error('실험 이름·상품·가격·실행 설정을 확인해 주세요. 빈 값은 사용할 수 없습니다.');}}
 const spec=structuredClone(defaults);spec.experiment_id=$('experiment-name').value.trim();spec.panel=filterParams();spec.seed=Number($('seed').value);spec.repeats=Number($('repeats').value);spec.batch_size=Number($('batch-size').value);spec.products=[product('a','A'),product('b','B')];spec.scenario.events=$('event').value?[{code:$('event').value,origin:'user_explicit_scenario'}]:[];spec.assumptions=$('fixture-budget').checked?structuredClone(defaults.assumptions):{};if($('panel-budget').value.trim()!==''){if(!$('panel-budget').checkValidity())throw new Error('예산은 0 이상의 정수 JPY로 입력해 주세요.');spec.assumptions.purchase_budget_jpy_minor=Number($('panel-budget').value);}return spec;
}
function explainBackend(){$('backend-explanation').textContent=$('backend').value==='mock'?'Mock는 동작 연결 검증용입니다. 명시적 fixture 예산의 구매 규칙과 반복 오류 사건의 이탈 규칙만 처리하고, 나머지는 판단 불가로 남깁니다.':$('backend').value==='julia'?'Julia-1 전용 결정모델은 주어진 선택지 중 하나를 고릅니다. 사유를 생성하지 않고 투입 입력 참조를 표시합니다. 초기 대비 사례에서 선택지 순서 민감성과 판단 불가를 관찰했습니다. 모델 softmax를 현실 구매 확률로 사용하지 않습니다.':'범용 지시 모델 Qwen이 제한된 JSON 선택을 생성합니다. 전용 결정모델은 아닙니다. 외부로 프로필을 보내지 않습니다. 초기 대비 사례에서 선택지 순서 민감성이 관찰됐고 상품 반응 정확도는 검증되지 않았으며, 응답 오류는 실패로 표시하고 mock으로 바꾸지 않습니다.';}
async function refreshHistory(){const runs=await api('/api/runs');$('history').innerHTML='<option value="">실험 선택</option>'+runs.map(run=>`<option value="${esc(run.id)}">${esc(run.experiment_id)} · ${esc(states[run.status]||run.status)} · ${run.cursor}/${run.total??'?'}</option>`).join('');if(currentRun)$('history').value=currentRun;}
async function showRun(){
 if(!currentRun||pollBusy)return;pollBusy=true;
 try{const status=await api('/api/runs/'+currentRun);$('run-state').textContent=states[status.status]||status.status;$('run-progress').textContent=`${status.cursor.toLocaleString()} / ${status.total?.toLocaleString()??'검사 중'}건 · ${status.backend_kind==='mock'?'MOCK':'실제 로컬 추론'} · 오류 ${status.backend_errors||0}건`;$('progress').max=status.total||1;$('progress').value=status.cursor;$('start-run').disabled=status.active||!panel?.matched_count;$('cancel-run').disabled=!status.active||status.cancel_requested;$('resume-run').disabled=status.active||status.cursor===status.total;$('retry-run').disabled=status.active||!status.backend_errors||status.cursor!==status.total;$('run-detail').textContent=status.cancel_requested?'중단 요청을 보냈습니다. 현재 모델 요청이 끝나면 완료 건수를 저장합니다.':status.error?`실패 원인: ${status.error}`:status.status==='completed'?'모든 판단을 저장했습니다. 결과와 보고서를 확인하세요.':'완료 결과와 체크포인트를 함께 저장합니다. 앱 재시작 뒤에도 저장된 실험에서 재개할 수 있습니다.';
  if(status.cursor>0&&(status.cursor!==lastCursor||status.status!==lastStatus||status.status==='retrying')){await showReport();lastCursor=status.cursor;}
  if(status.status!==lastStatus){lastStatus=status.status;await refreshHistory();}
 }catch(error){showError(error);}finally{pollBusy=false;}
}
async function showReport(){
 const reportRun=currentRun;const report=await api('/api/runs/'+reportRun+'/report');if(reportRun!==currentRun)return;$('empty-results').hidden=true;$('report-content').hidden=false;$('exports').hidden=false;
 for(const format of['json','csv','md'])$('export-'+format).href=`/api/runs/${currentRun}/export?format=${format}`;$('export-spec').href=`/api/runs/${currentRun}/spec`;
 $('report-summary').textContent=`${report.backend_kind==='mock'?'MOCK 연결 검증 결과':'실제 로컬 추론 결과'} · ${report.completed_jobs.toLocaleString()}/${report.planned_jobs.toLocaleString()}건 · 결과가 있는 인물 ${report.observed_personas.toLocaleString()}명. 구조 검사 통과 ${report.valid_decisions}건 · 백엔드 오류 ${report.backend_errors}건. 판단 불가는 구조 유효 판단의 분모에 포함하며 오류는 따로 셉니다.${!['completed','completed_with_errors'].includes(report.status)?' 아직 일부 결과이며 먼저 처리된 인물에 치우칠 수 있습니다.':''}`;
 const conflicts=report.consistency_warnings?.purchase_above_explicit_budget||0;$('consistency-warning').hidden=conflicts===0;$('consistency-warning').textContent=`명시 예산과 충돌: ${conflicts}건이 예산을 넘는 가격에서 구매를 선택했습니다. 원래 선택과 분모는 유지했습니다. 모델 반응을 사실이나 구매 확률로 해석하지 마세요.`;
 $('result-description').textContent=`저장된 실험: ${report.experiment_id}. 현재 입력 수정은 이 저장 결과에 반영되지 않습니다.`;
 $('comparison').innerHTML=defaults.questions.map(question=>{const group=id=>report.groups.find(g=>g.product_id===id&&g.question_id===question.id);return`<div class="comparison-row"><h3>${esc(domains[question.domain])}</h3>${['A','B'].map(id=>{const g=group(id);return`<div><strong>상품 ${id}</strong> <span class="helper">구조 유효 ${g?.completed||0}건 · 오류 ${g?.backend_errors||0}건</span>${question.choices.map(choice=>{const n=g?.choice_counts[choice]||0;const share=g?.completed?n/g.completed:0;return`<div class="choice-line"><span>${esc(choices[choice]||choice)}</span><span class="bar"><span class="bar-fill ${choice==='unknown'?'unknown':''}" data-share="${share}"></span></span><span>${n} · ${Math.round(share*100)}%</span></div>`;}).join('')}</div>`;}).join('')}</div>`;}).join('');
 document.querySelectorAll('.bar-fill').forEach(bar=>{bar.style.width=(Number(bar.dataset.share)*100)+'%';});
 $('transitions').innerHTML=report.paired_transition_count?`<p class="helper">A와 B 모두 완료된 같은 인물·질문·반복 ${report.paired_transition_count}쌍</p><div class="transition-list">${report.paired_purchase_transitions.map(t=>`<div class="transition-item">${esc(choices[t.from]||t.from)} → ${esc(choices[t.to]||t.to)} <strong>${t.count}쌍</strong></div>`).join('')}</div>`:'<p>아직 A와 B의 구매 판단이 모두 완료된 짝이 없습니다.</p>';
 $('examples').innerHTML=report.examples.map(r=>`<tr><td class="uuid">${esc(r.uuid.slice(0,10))}…</td><td>${esc(r.product_id)} · ${esc(domains[r.domain])}</td><td>${esc(r.decision?(choices[r.decision.choice]||r.decision.choice):'백엔드 오류')}</td><td>${r.decision?r.decision.reason_codes.map(esc).join(', '):esc(r.backend_error?.type)}</td><td>${r.decision?((r.decision.evidence_semantics==='supplied_input_only'?'투입 입력 참조: ':'')+(r.decision.evidence_refs.map(esc).join(', ')||'근거 정보 부족')):esc(r.backend_error?.message)}</td><td><button class="quiet" data-job="${esc(r.job_id)}" data-run="${esc(reportRun)}">조건 검토</button></td></tr>`).join('');
 $('report-meta').textContent=JSON.stringify({source:report.source,input_condition:report.input_condition,assumptions:report.assumptions,scenario:report.scenario,limitations:report.limitations},null,2);
}
$('examples').addEventListener('click',async event=>{const button=event.target.closest('[data-job]');if(!button)return;try{const detail=await api(`/api/runs/${button.dataset.run}/jobs/${button.dataset.job}`);$('decision-json').textContent=JSON.stringify(detail,null,2);$('decision-detail').hidden=false;$('decision-detail').open=true;}catch(error){showError(error);}});
function guarded(fn){return async(...args)=>{try{await fn(...args);}catch(error){showError(error);}};}
$('filter-form').addEventListener('submit',guarded(async event=>{event.preventDefault();offset=0;await loadPanel();}));
$('clear-filters').addEventListener('click',guarded(async()=>{for(const id of['prefecture','age-min','age-max','query'])$(id).value='';offset=0;await loadPanel();}));
$('pack').addEventListener('change',guarded(selectPack));
$('import-sample').addEventListener('click',guarded(async()=>{const button=$('import-sample');button.disabled=true;button.textContent='공개 데이터 확인 중…';clearError();try{const pack=await api('/api/import',{dataset:'nemotron-japan-viewer'});packs=await api('/api/packs');$('pack').innerHTML=packs.map(p=>`<option value="${esc(p.id)}">${esc(p.name)} · ${p.record_count}명</option>`).join('');$('pack').value=pack.id;await selectPack();}finally{button.disabled=false;button.textContent='공개 소형 샘플 가져오기';}}));
$('prev-page').addEventListener('click',guarded(async()=>{offset=Math.max(0,offset-20);await loadPanel();}));$('next-page').addEventListener('click',guarded(async()=>{offset+=20;await loadPanel();}));
$('personas').addEventListener('click',event=>{const button=event.target.closest('[data-persona]');if(!button)return;$('persona-json').textContent=JSON.stringify(previewItems[Number(button.dataset.persona)],null,2);$('persona-detail').hidden=false;$('persona-detail').open=true;});
$('repeats').addEventListener('input',updateEstimate);$('backend').addEventListener('change',explainBackend);
$('swap-products').addEventListener('click',()=>{const a=product('a','A'),b=product('b','B');fillProduct('a',b);fillProduct('b',a);});
$('start-run').addEventListener('click',guarded(async()=>{clearError();const spec=buildSpec();$('start-run').disabled=true;try{const data=await api('/api/runs',{dataset_id:$('pack').value,backend:$('backend').value,spec});currentRun=data.id;lastCursor=-1;lastStatus='';await showRun();await refreshHistory();}finally{if(!currentRun)$('start-run').disabled=false;}}));
$('cancel-run').addEventListener('click',guarded(async()=>{await api(`/api/runs/${currentRun}/cancel`,{});await showRun();}));$('resume-run').addEventListener('click',guarded(async()=>{clearError();await api(`/api/runs/${currentRun}/resume`,{});await showRun();}));
$('retry-run').addEventListener('click',guarded(async()=>{await api(`/api/runs/${currentRun}/retry`,{});await showRun();}));
$('history').addEventListener('change',guarded(async()=>{currentRun=$('history').value||null;lastCursor=-1;lastStatus='';if(currentRun)await showRun();}));
document.querySelectorAll('nav a').forEach(link=>link.addEventListener('click',()=>{document.querySelectorAll('nav a').forEach(a=>a.classList.toggle('active',a===link));}));
guarded(async()=>{[packs,defaults]=await Promise.all([api('/api/packs'),api('/api/default-experiment')]);$('pack').innerHTML=packs.map(pack=>`<option value="${esc(pack.id)}">${esc(pack.name)} · ${pack.record_count}명</option>`).join('');$('pack').value=packs.some(p=>p.id==='nemotron-japan-sample')?'nemotron-japan-sample':packs[0]?.id;fillProduct('a',defaults.products[0]);fillProduct('b',defaults.products[1]);await selectPack();const runtime=await api('/api/backend-status');$('runtime-state').textContent=runtime.julia_available?'Julia-1 전용 모델 연결됨':runtime.local_available?'Qwen 로컬 모델 연결됨':'MOCK 사용 가능 · 로컬 모델 미연결';$('local-option').disabled=!runtime.local_available;$('julia-option').disabled=!runtime.julia_available;await refreshHistory();setInterval(showRun,1000);})();

let parquetConfig=null,currentImport=null,importPollBusy=false,installedImportPack=null;
const importStates={preparing:'준비',running:'실행 중',paused:'일시 중단',interrupted:'이전 프로세스 중단',failed:'실패',completed:'완료'};
function fillParquetFiles(){
 if(!parquetConfig)return;const official=$('parquet-kind').value==='official_parquet';const entries=official?parquetConfig.official_shards:parquetConfig.local_files;const previous=$('parquet-file').value;
 $('parquet-file').innerHTML=entries.map(entry=>`<option value="${esc(entry.filename)}">${esc(entry.filename)}${official?' · '+(entry.bytes/1024/1024).toFixed(1)+'MiB':' · '+esc(entry.license_id)}</option>`).join('');
 if(entries.some(entry=>entry.filename===previous))$('parquet-file').value=previous;
 $('parquet-start').disabled=!parquetConfig.available||!entries.length;
}
async function refreshImports(){
 [parquetConfig]=await Promise.all([api('/api/parquet-config')]);fillParquetFiles();$('parquet-availability').textContent=parquetConfig.available?'PyArrow 연결됨 · 변환 배치 256행은 메모리 설정이며 인원 제한이 아닙니다. 로컬 파일은 data/inbox/<파일>.parquet 와 <파일>.parquet.source.json으로 준비하세요.':'PyArrow 미준비 · docs/PARQUET.md의 격리 설치 절차를 확인하세요. 기존 JSONL 데이터팩과 Mock은 사용할 수 있습니다.';
 const entries=await api('/api/parquet-imports');$('parquet-history').innerHTML='<option value="">선택</option>'+entries.map(entry=>`<option value="${esc(entry.id)}">${esc(entry.id.slice(0,8))} · ${esc(importStates[entry.status]||entry.status)} · ${entry.rows}/${entry.total_rows??'?'}</option>`).join('');if(currentImport)$('parquet-history').value=currentImport;
}
async function showImport(){
 if(!currentImport||importPollBusy)return;importPollBusy=true;
 try{const state=await api('/api/parquet-imports/'+currentImport);const download=state.phase==='downloading';const value=download?state.download_bytes:state.rows;const total=download?state.download_total_bytes:state.total_rows;
 $('parquet-state').textContent=`${importStates[state.status]||state.status} · ${download?'다운로드':'변환'} ${Number(value||0).toLocaleString()}/${total?.toLocaleString()??'?'}${download?' bytes':'행'}${state.error?' · '+state.error:''}${state.cancel_requested?' · 현재 블록/배치 저장 후 중단':''}${state.external_active?' · 외부 CLI 실행 중: Ctrl+C로 중단':''}`;
 const option=[...$('parquet-history').options].find(option=>option.value===currentImport);if(option)option.textContent=`${currentImport.slice(0,8)} · ${importStates[state.status]||state.status} · ${state.rows}/${state.total_rows??'?'}`;
 $('parquet-progress').max=total||1;$('parquet-progress').value=value||0;$('parquet-cancel').disabled=!state.active||state.cancel_requested||state.external_active;$('parquet-resume').disabled=state.active||state.status==='completed';$('parquet-start').disabled=state.active||!parquetConfig?.available||!$('parquet-file').value;
 if(state.status==='completed'&&state.pack_id!==installedImportPack){installedImportPack=state.pack_id;packs=await api('/api/packs');$('pack').innerHTML=packs.map(pack=>`<option value="${esc(pack.id)}">${esc(pack.name)} · ${pack.record_count}명</option>`).join('');$('pack').value=state.pack_id;await selectPack();await refreshImports();}
 }finally{importPollBusy=false;}
}
$('parquet-kind').addEventListener('change',fillParquetFiles);
$('parquet-refresh').addEventListener('click',guarded(async()=>{await refreshImports();await showImport();}));
$('parquet-start').addEventListener('click',guarded(async()=>{clearError();$('parquet-start').disabled=true;try{const kind=$('parquet-kind').value;const body=kind==='official_parquet'?{kind,shard:$('parquet-file').value}:{kind,filename:$('parquet-file').value};const created=await api('/api/parquet-imports',body);currentImport=created.id;await refreshImports();await showImport();}finally{if(!currentImport)fillParquetFiles();}}));
$('parquet-history').addEventListener('change',guarded(async()=>{currentImport=$('parquet-history').value||null;await showImport();}));
$('parquet-cancel').addEventListener('click',guarded(async()=>{await api('/api/parquet-imports/'+currentImport+'/cancel',{});await showImport();}));
$('parquet-resume').addEventListener('click',guarded(async()=>{clearError();await api('/api/parquet-imports/'+currentImport+'/resume',{});await showImport();}));
guarded(async()=>{await refreshImports();setInterval(guarded(showImport),1000);})();
