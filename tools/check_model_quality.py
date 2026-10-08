"""Real local inference controls for memo-product judgments; no mock fallback."""
import argparse,copy,json,sys,time
from collections import Counter
from dataclasses import asdict,replace
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from persona_desktop.model import BundledModel
from persona_lab.contracts import digest
from persona_lab.runner import jobs
from persona_lab.responses import LINKED_QUESTIONS,LINKED_SCENARIO_ID,price_bands
from persona_lab.backends import LocalLLMBackend

parser=argparse.ArgumentParser();parser.add_argument('--assets',type=Path,default=ROOT/'assets');parser.add_argument('--input',type=Path);parser.add_argument('--sample',type=int,default=0);parser.add_argument('--output',type=Path,default=ROOT/'verification/model-quality.json');args=parser.parse_args()
source=json.loads((ROOT/'assets/data/nemotron-japan-sample.json').read_text());document='## 주요 기능\n\n개인 메모를 검색하고 태그로 정리합니다. 메모는 기기에 저장하며 파일로 내보냅니다.\n\n## 도입 조건·제약\n\nmacOS 14 이상에서만 사용합니다. Windows와 스마트폰은 지원하지 않습니다. 계정과 인터넷은 필요하지 않습니다. 동기화와 팀 공유 기능은 없습니다.'
spec={'schema_version':'0.1','experiment_id':'f'*32,'mode':'independent_comparison','panel':{'selection':'all'},'seed':17,'repeats':1,'batch_size':1,'products':[{'id':'a'*32,'name':'메모 도구','document':document,'intro':document,'features':[],'price':{'amount_minor':2000,'currency':'JPY','billing':'one_time'},'valuation_unit':{'currency':'JPY','billing':'one_time'},'valuation_bands':price_bands('JPY')}],'questions':LINKED_QUESTIONS,'scenario':{'id':LINKED_SCENARIO_ID,'initial_state_id':'initial-v1','events':[]},'assumptions':{}}
if args.input:
    snapshot=json.loads(args.input.read_text());spec={**snapshot['spec'],'questions':LINKED_QUESTIONS,'scenario':spec['scenario'],'batch_size':1};source=snapshot['source']
planned=list(jobs(ROOT/'assets/data'/source['data_file'],source,spec));home=ROOT/'build/model-quality-home';home.mkdir(parents=True,exist_ok=True);model=BundledModel(args.assets.resolve(),home);checks=[];calls=[]
try:
    model.start('http://127.0.0.1:1');deadline=time.monotonic()+60
    while model.status()['phase']=='starting' and time.monotonic()<deadline:time.sleep(.2)
    if model.status()['phase']!='ready':raise RuntimeError(model.status())
    backend=model.backend(linked=True)
    def audit(event,identifier,value):
        if event=='start':calls.append({'job_id':identifier,**value});return len(calls)-1
        calls[identifier].update(value)
    backend.audit=audit
    def call(job,label,expected=None,reverse=False,expected_amount=None):
        actual=None;error=None;started=time.monotonic();original=backend.request_body
        if reverse:
            def reordered(candidate):
                body,*rest=original(candidate)
                for branch in body['response_format']['json_schema']['schema']['oneOf']:branch['properties']['assessment']['properties']['choice']['enum'].reverse()
                return (body,*rest)
            backend.request_body=reordered
        try:actual=asdict(backend.decide(job))
        except ValueError as problem:error={'type':type(problem).__name__,'message':str(problem)}
        finally:backend.request_body=original
        passed=error is None and (expected is None or actual['choice'] in expected) and (expected_amount is None or (actual.get('valuation') or {}).get('amount_minor')==expected_amount)
        row={'case':label,'domain':job.question['domain'],'job_id':job.job_id,'persona_id':job.persona.persona_id,'expected':sorted(expected) if expected is not None else None,'expected_amount_minor':expected_amount,'decision':actual,'error':error,'passed':passed,'seconds':round(time.monotonic()-started,2)};checks.append(row)
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps({'model':model.info,'passed':all(item['passed'] for item in checks),'checks':checks,'model_calls':calls,'scope':'Behavioral consistency and instruction-following controls, not consumer calibration or representative-sample validation.'},ensure_ascii=False,indent=2)+'\n')
        print(json.dumps({'case':label,'domain':row['domain'],'choice':actual['choice'] if actual else None,'valuation':actual['valuation'] if actual else None,'passed':passed,'error':error,'seconds':row['seconds']},ensure_ascii=False),flush=True)
        return actual
    def chain(person,label,usage_expected,fair_expected,prices,purchase_expected,reverse=False):
        prior={}
        for index,expected in ((0,usage_expected),(1,fair_expected)):
            base=planned[index];job=replace(base,job_id=digest([label,index,reverse]),persona=person)
            answer=call(job,label,expected,reverse)
            if answer:prior[job.question['domain']]={**{key:answer.get(key) for key in ('choice','reason','valuation','missing_information')},'job_id':job.job_id}
        for price,expected in zip(prices,purchase_expected):
            base=planned[2];job=replace(base,job_id=digest([label,price,reverse]),persona=person,product={**base.product,'price':{**base.product['price'],'amount_minor':price}},assessments=prior)
            call(job,label+'_'+str(price),expected,reverse)
    original=planned[0].persona
    profiles=[
        ('need',{'persona':'매일 macOS 14 PC에서 개인 메모를 작성한다. 메모를 검색하고 태그로 분류할 도구가 필요하다. 이런 검색·태그 도구의 적정가격은 일시불 1,000 JPY라고 생각한다. 2,000 JPY를 넘으면 구매하지 않겠다고 명시했다.','occupation':'문서 편집자','current_method':'종이 메모에서 내용을 찾기 어렵다.','operating_system':'macOS 14'}, {'use'},{'price_1'},[0,500,2000000],[{'buy'},{'buy'},{'decline'}]),
        ('no_need',{'persona':'개인 메모를 전혀 작성하지 않는다. 새 메모 앱을 추가로 사용할 의향이 없으며 무료라도 사용하지 않겠다고 명시했다.','occupation':'조리사'}, {'not_use'},{'price_0','unknown'},[0],[{'decline'}]),
        ('windows_only',{'persona':'Windows PC와 Android 스마트폰만 사용한다. Mac을 구입하거나 빌릴 계획이 없고 macOS 전용 앱은 설치할 수 없다.','occupation':'문서 편집자','operating_system':'Windows와 Android'}, {'not_use'},{'price_0','unknown'},[0],[{'decline'}]),
        ('missing_context',{'age':35,'sex':'女'}, {'unknown'},{'unknown'},[2000],[{'unknown'}]),
    ]
    for label,raw,use,fair,prices,purchases in profiles:
        person=replace(original,raw=raw,content_hash=digest(raw),persona_id=digest(['control',label]))
        chain(person,label,use,fair,prices,purchases)
        if label=='need':chain(person,label+'_order_reversed',use,fair,prices,purchases,True)
    usd_raw={'persona':'매일 macOS 14 PC 에서 메모를 작성한다. 검색과 태그 기능이 필요하며 이 메모 도구에 적정하다고 생각하는 가격은 일시불 9.99 USD 라고 명시했다.','occupation':'문서 편집자'}
    usd_person=replace(original,raw=usd_raw,content_hash=digest(usd_raw),persona_id=digest(['control','USD']))
    usd_base=planned[1];usd_job=replace(usd_base,job_id=digest(['USD','valuation']),persona=usd_person,product={**usd_base.product,'valuation_unit':{'currency':'USD','billing':'one_time'},'valuation_bands':price_bands('USD')})
    call(usd_job,'USD_minor_units',{'price_0'},expected_amount=999)
    selected=[]
    for job in planned:
        if job.persona.persona_id not in {p.persona_id for p in selected}:selected.append(job.persona)
    for person in selected[:args.sample]:chain(person,'sample_'+person.uuid,{'use','not_use','unknown'},{'price_0','price_1','price_2','price_3','unknown'},[2000,2000000],[{'buy','defer','decline','unknown'},{'defer','decline','unknown'}])
    failures=[{'case':item['case'],'domain':item['domain'],'error':item['error']} for item in checks if not item['passed']]
    print(json.dumps({'checks':len(checks),'failed':len(failures),'failures':failures},ensure_ascii=False),flush=True)
    if failures:raise SystemExit(1)
finally:model.close()
