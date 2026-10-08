"""Exercise the packaged Python, data and real bundled model without host imports."""
import argparse, hashlib, json, os, re, sqlite3, subprocess, time, urllib.request, uuid as uuid_module
from pathlib import Path

root=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('--app',type=Path,default=root/'build/Persona Lab.app');parser.add_argument('--home',type=Path,default=root/'build/clef-smoke-home');args=parser.parse_args()
app=args.app.resolve();resources=app/'Contents/Resources'
home=args.home.resolve();home.mkdir(parents=True,exist_ok=True)
env={**os.environ,'PYTHONHOME':str(app/'Contents/Frameworks/Python.framework/Versions/3.12'),'PYTHONPATH':str(resources/'src'),'PYTHONNOUSERSITE':'1','PYTHONDONTWRITEBYTECODE':'1'}
env.pop('__PYVENV_LAUNCHER__',None)
log=(home/'service.log').open('ab')
process=subprocess.Popen([str(app/'Contents/MacOS/PythonRunner'),'-s','-m','persona_desktop.server','--root',str(resources),'--home',str(home)],env=env,stdout=subprocess.PIPE,stderr=log,text=True)
started=time.monotonic();receipt={}
try:
    line=process.stdout.readline();assert line,'packaged application failed before startup'
    base=json.loads(line)['url']
    with urllib.request.urlopen(base,timeout=5) as response:
        token=re.search(r'data-token="([a-f0-9]+)"',response.read().decode()).group(1)
    def api(path,body=None):
        request=urllib.request.Request(base+path,data=None if body is None else json.dumps(body).encode(),headers={'X-Persona-Token':token,'Content-Type':'application/json'})
        with urllib.request.urlopen(request,timeout=100) as response:return json.load(response)
    for _ in range(240):
        state=api('/api/state')
        if state['model']['phase']=='ready':break
        if state['model']['phase']=='failed':raise AssertionError(state['model']['error'])
        time.sleep(.25)
    else:raise AssertionError('bundled model did not become ready')
    assert state['source']['record_count']==53
    panel=api('/api/panel',{'panel':{'selection':'all'}})
    uuid=panel['items'][0]['uuid']
    draft=api('/api/experiments',{})
    draft['items'][0]['name']='メモ整理ツール'
    draft['items'][0]['pricing']={'state':'free','amount':'','currency':'JPY','billing':'one_time'}
    draft['items'][0]['document']='## 해결할 문제\n\n散らばったメモを探す時間がかかります。\n\n## 주요 기능\n- 検索\n- タグ整理\n- ローカル保存\n\n## 사용 방법\n\nアプリを起動してメモを登録します。\n\n## 도입 조건·제약\n\nmacOSで動作します。データは端末に保存します。'
    draft['items'].append({'id':uuid_module.uuid4().hex,'name':'メモ整理ツール','document':draft['items'][0]['document'],'pricing':{'state':'paid','amount':'2000','currency':'JPY','billing':'one_time'}})
    draft['panel']={'selection':'filter','query':uuid}
    draft=api('/api/experiments/'+draft['id']+'/save',draft)
    api('/api/experiments/'+draft['id']+'/start',{})
    for _ in range(720):
        status=api('/api/experiments/'+draft['id'])['run']
        if not status['active']:break
        time.sleep(.25)
    else:raise AssertionError('real inference did not complete')
    assert status['cursor']==status['total']==6,status
    report=api('/api/experiments/'+draft['id']+'/report')
    assert report['backend_kind']=='dedicated_local_decision'
    assert report['backend_id'].endswith('finite-choice-v1')
    assert report['products'][0]['price']['amount_minor']==0
    assert report['products'][1]['price']['amount_minor']==2000
    assert all('어떤 문제를' not in p['document'] for p in report['products'])
    assert report['valid_decisions']==6 and report['backend_errors']==0,report
    prefix='/api/experiments/'+draft['id']
    page=api(prefix+'/results?limit=25')
    assert page['count']==3 and all(len(row['cells'])==2 and all(row['cells']) for row in page['rows'])
    assert report['scenario']['id']=='product-decision-v1'
    assert report['assumptions']=={}
    response=api(prefix+'/responses')
    assert response['count']==1 and len(response['people'][0]['items'])==2
    assert all(item['purchase']['choice']!='not_run' for item in response['people'][0]['items'])
    decisions=[cell['record']['decision'] for row in page['rows'] for cell in row['cells']]
    assert all(decision.get('valuation') is None and decision['probability_semantics']=='model_option_distribution' and decision['option_probabilities'] and decision['evidence_semantics']=='supplied_input_only' for decision in decisions)
    assert all(decision['missing_information'] if decision['choice']=='unknown' else decision['reason']=='' for decision in decisions)
    assert all(cell['record']['execution']['max_steps']==1 for row in page['rows'] for cell in row['cells'])
    job=page['rows'][0]['cells'][0]['record']['job_id']
    detail=api(prefix+'/jobs/'+job)
    assert detail['offered_product']['document']==draft['items'][0]['document']
    assert detail['product']['price'] is None
    assert 1<=len(detail['model_calls'])<=2 and all(call['response'] is not None for call in detail['model_calls'])
    assert not detail['record']['decision']['evidence']
    with sqlite3.connect(home/'experiments'/draft['id']/'run.sqlite') as db:
        calls=db.execute('SELECT request,response FROM model_calls WHERE response IS NOT NULL AND finished_at IS NOT NULL').fetchall()
    assert len(calls)==6+sum(decision['choice']=='unknown' for decision in decisions)
    assert all(json.loads(response)['usage']['output_tokens']==0 and 'messages' not in json.loads(request) for request,response in calls)
    directory=home/'experiments'/draft['id']
    def original_records():
        with sqlite3.connect(directory/'run.sqlite') as db:return db.execute('SELECT job_id,payload FROM results ORDER BY ordinal').fetchall()
    before=original_records();frozen_hash=hashlib.sha256((directory/'run.json').read_bytes()).hexdigest()
    api(prefix+'/jobs/'+job+'/review',{'revision':0,'marked':True,'note':'패키지 검증 메모'})
    assert api(prefix+'/results?mode=marked')['count']==1
    assert original_records()==before and hashlib.sha256((directory/'run.json').read_bytes()).hexdigest()==frozen_hash
    diff=api(prefix+'/documents?baseline='+draft['items'][0]['id']+'&item='+draft['items'][1]['id'])
    assert any(row['kind']=='remove' and '무료' in row['text'] for row in diff['rows'])
    assert any(row['kind']=='add' and '2000' in row['text'] for row in diff['rows'])
    for fmt in ('md','csv','json','spec','reviews'):
        value=api(prefix+'/export',{'format':fmt});assert len(value['body'])>100
        if fmt in ('md','json','reviews'):assert '패키지 검증 메모' in value['body']
    oversized=api('/api/experiments',{});oversized['title']='입력 한도 검증';oversized['panel']=draft['panel']
    oversized['items'][0].update(name='긴 문서',document='あ'*20000,pricing={'state':'free','amount':'','currency':'JPY','billing':'one_time'})
    api('/api/experiments/'+oversized['id']+'/save',oversized)
    try:api('/api/experiments/'+oversized['id']+'/start',{})
    except urllib.error.HTTPError as problem:
        message=json.load(problem)['error'];assert '한도' in message or '너무 깁니다' in message,message
    else:raise AssertionError('oversized model input was accepted')
    assert api('/api/experiments/'+oversized['id'])['run'] is None
    api('/api/experiments/'+oversized['id']+'/delete',{})
    receipt={'status':'passed','bundle':str(app),'home':str(home),'model':state['model']['info']['name'],'backend_id':report['backend_id'],'source_rows':53,'panel_rows':1,'items':2,'processed':6,'valid_decisions':report['valid_decisions'],'backend_errors':report['backend_errors'],'model_calls':len(calls),'all_output_tokens_zero':True,'oversized_input_rejected_before_run':True,'elapsed_seconds':round(time.monotonic()-started,2),'experiment_id':draft['id'],'choices':[{kind:item[kind]['choice'] for kind in ('usage','fair_price','purchase')} for item in response['people'][0]['items']],'scope':'packaged dedicated decision head, actual free and paid finite inference, linked prior codes, option distributions and full raw audit, unknown followup, joined results, frozen originals, isolated annotations, five exports and preflight rejection; no consumer accuracy claim'}
    (root/'verification').mkdir(exist_ok=True)
    (root/'verification/packaged-clef-model.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(receipt,ensure_ascii=False),flush=True)
finally:
    process.terminate()
    try:process.wait(timeout=15)
    except subprocess.TimeoutExpired:process.kill();process.wait()
    log.close()
