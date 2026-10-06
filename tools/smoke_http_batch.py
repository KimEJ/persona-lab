"""Actual fixed-loopback app batch/resume check; no browser or external calls."""
import json
import sqlite3
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

root = Path(__file__).resolve().parents[1]
base = 'http://127.0.0.1:8787'

def api(path, data=None, service=base):
    request = urllib.request.Request(service + path, data=None if data is None else json.dumps(data).encode(), headers={'Content-Type': 'application/json', 'X-Persona-Lab': 'demo-v1'}, method='GET' if data is None else 'POST')
    with urllib.request.urlopen(request, timeout=30) as response: return json.load(response)

def await_status(identifier, predicate, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = api('/api/runs/' + identifier)
        if predicate(status): return status
        time.sleep(.05)
    raise AssertionError(status)

def rows(identifier):
    with sqlite3.connect(root / 'runs' / identifier / 'run.sqlite') as db:
        return dict(db.execute('SELECT job_id,payload FROM results ORDER BY ordinal'))

spec = api('/api/default-experiment')
spec.update(experiment_id='julia-public53-batch-cancel-resume', batch_size=32, assumptions={'purchase_budget_jpy_minor': 1500})
spec['scenario']['events'] = [{'code': 'repeated_crash', 'origin': 'explicit_test_scenario'}]
before = api('/health', service='http://127.0.0.1:8082')['stats']
identifier = api('/api/runs', {'dataset_id': 'nemotron-japan-sample', 'backend': 'julia', 'spec': spec})['id']
await_status(identifier, lambda status: status['cursor'] >= 32)
api('/api/runs/' + identifier + '/cancel', {})
paused = await_status(identifier, lambda status: not status['active'])
assert 0 < paused['cursor'] < 742 and paused['cursor'] % 32 == 0, paused
saved = rows(identifier)
api('/api/runs/' + identifier + '/resume', {})
completed = await_status(identifier, lambda status: not status['active'])
assert completed['status'] == 'completed' and completed['cursor'] == 742 and completed['backend_errors'] == 0, completed
current = rows(identifier)
assert len(current) == 742 and all(current[key] == payload for key, payload in saved.items())
resumed_stats = api('/health', service='http://127.0.0.1:8082')['stats']
# Same logical experiment, another store: compare against uninterrupted output.
started = time.monotonic()
baseline_id = api('/api/runs', {'dataset_id': 'nemotron-japan-sample', 'backend': 'julia', 'spec': spec})['id']
baseline = await_status(baseline_id, lambda status: not status['active'])
wall = time.monotonic() - started
assert baseline['status'] == 'completed' and rows(baseline_id) == current, baseline
report = api('/api/runs/' + identifier + '/report')
assert report['observed_personas'] == 53 and report['valid_decisions'] == 742
for format in ('json', 'csv', 'md'):
    with urllib.request.urlopen(base + '/api/runs/' + identifier + '/export?format=' + format) as response:
        output = response.read(); assert response.status == 200 and len(output) > 100
    (root / f'verification/julia-public53-batch-report.{format}').write_bytes(output)
after = api('/health', service='http://127.0.0.1:8082')['stats']
receipt = {'verified_at': datetime.now(timezone.utc).isoformat(), 'scope': 'Actual HTTP app -> keyed Julia batch -> SQLite -> report/export', 'engine': '0.3.0', 'run_id': identifier, 'baseline_run_id': baseline_id, 'panel_personas': 53, 'planned_jobs': 742, 'valid_decisions': report['valid_decisions'], 'backend_errors': report['backend_errors'], 'budget_conflicts': report['consistency_warnings']['purchase_above_explicit_budget'], 'paused_cursor': paused['cursor'], 'unchanged_saved_rows': len(saved), 'resumed_equals_uninterrupted': True, 'resumed_service_requests': resumed_stats['predict_requests'] - before['predict_requests'], 'resumed_requested_rows': resumed_stats['requested_rows'] - before['requested_rows'], 'uninterrupted_service_requests': after['predict_requests'] - resumed_stats['predict_requests'], 'uninterrupted_requested_rows': after['requested_rows'] - resumed_stats['requested_rows'], 'max_inference_group_size': after['max_group_size'], 'uninterrupted_wall_seconds': wall, 'app_processed_jobs_per_second': 742 / wall, 'peak_note': 'Single 53-person preview workload, warmed resident model; not million-person performance or consumer accuracy.'}
(root / 'verification/http-julia-batch-resume.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(receipt, ensure_ascii=False))
