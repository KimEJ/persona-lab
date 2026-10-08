"""Actual Mac CPU finite-choice smoke; repeated rows measure throughput, not accuracy."""
import json
import statistics
import time
import urllib.request
from pathlib import Path
from datetime import datetime, timezone

from persona_lab.backends import JuliaBackend, LocalLLMBackend, FixtureBackend, julia_row
from persona_lab.runner import jobs, run
from persona_lab.reports import summarize, export

root = Path(__file__).resolve().parents[1]
source = json.loads((root / 'data/packs/nemotron-japan-sample.json').read_text())
spec = json.loads((root / 'examples/experiment.json').read_text())
spec.update(experiment_id='japanese-model-comparison-explicit-budget', panel={'selection':'filter','query':'09ae83ddc11745f6b995113fe7ed4a77'}, assumptions={'purchase_budget_jpy_minor':1500})
job = next(job for job in jobs(root / 'data/packs/nemotron-japan-sample.jsonl', source, spec) if job.question['domain'] == 'purchase')
row = julia_row(job)

def predict(rows):
    request = urllib.request.Request('http://127.0.0.1:8082/predict', data=json.dumps({'rows':rows},ensure_ascii=False).encode(), headers={'Content-Type':'application/json','X-Persona-Lab':'demo-v1'}, method='POST')
    start = time.monotonic()
    with urllib.request.urlopen(request,timeout=120) as response: body = json.load(response)
    assert len(body['results']) == len(rows)
    assert all(type(answer['index']) is int and 0 <= answer['index'] < len(rows[i]['options']) for i,answer in enumerate(body['results']))
    return body, time.monotonic()-start

warm, _ = predict([row])
baseline = warm['results'][0]['index']
measurements = []
for batch in (1,8,32):
    elapsed, server_elapsed, peaks, indices = [],[],[],[]
    for _ in range(3):
        response, duration = predict([row]*batch)
        elapsed.append(duration);server_elapsed.append(response['metrics']['elapsed_seconds']);peaks.append(response['metrics']['peak_rss_mib']);indices.extend(r['index'] for r in response['results'])
    median = statistics.median(elapsed)
    measurements.append({'batch_size':batch,'repetitions':3,'median_wall_seconds':median,'rows_per_second':batch/median,'median_server_seconds':statistics.median(server_elapsed),'peak_server_rss_mib':max(peaks),'valid_choices':len(indices),'total_choices':batch*3,'same_choice_as_batch1':sum(i==baseline for i in indices),'encoding_tokens':response['encoding'][0]['tokens'],'state_truncated':response['encoding'][0]['stateTruncated'],'options_truncated':response['encoding'][0]['optionsTruncated']})
reversed_row={**row,'options':list(reversed(row['options']))}
reverse, _ = predict([reversed_row])
reverse_semantic_index=len(row['options'])-1-reverse['results'][0]['index']
comparisons={}
for name,backend in [('mock',FixtureBackend()),('qwen',LocalLLMBackend()),('julia',JuliaBackend())]:
    database=root/f'runs/explicit-budget-{name}-engine02.sqlite'
    status=run(root/'data/packs/nemotron-japan-sample.jsonl',source,spec,database,backend)
    report=summarize(database)
    comparisons[name]={'status':status,'unknown':sum(g['unknown'] for g in report['groups']),'purchase':[g for g in report['groups'] if g['domain']=='purchase']}
    (root/f'verification/{name}-explicit-budget-report.json').write_text(export(database,'json')[0])
receipt={'verified_at':datetime.now(timezone.utc).isoformat(),'model':'Julia-1','revision':'a85b127321d580d65176c89ced8273f305745d85','device':'cpu','strict_encoding':True,'native_router_build':False,'input_language':'Japanese','unique_source_personas':1,'workload':'identical repeated purchase row; throughput measurement only','measurements':measurements,'option_order':{'baseline_semantic_choice':job.question['choices'][baseline],'reversed_semantic_choice':job.question['choices'][reverse_semantic_index],'changed':baseline!=reverse_semantic_index},'same_case_comparison':comparisons,'limitations':['Finite-choice validity is not consumer-behavior accuracy.','This one repeated profile does not establish general option-order robustness.','Qwen and Julia have different adapter prompt formats.','Peak RSS is the Julia service process high-water mark, not total device memory.','Backend batch benchmark is separate from the current sequential per-job app calls.']}
(root/'verification/julia-benchmark.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(receipt,ensure_ascii=False,indent=2))
