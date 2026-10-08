"""Optional isolated resident Julia CPU service. Never imported by the stdlib app."""
import json
import os
import threading
import resource
import sys
import time
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['TRANSFORMERS_OFFLINE'] = '1'
os.environ['JULIA_CPU_THREADS'] = '4'
root = Path(__file__).resolve().parents[1]
# Use the verified local source directly; do not rely on editable .pth hooks.
sys.path.insert(0, str(root / 'models/Julia-1'))
from julia import load_model

engine = load_model(root / 'models/Julia-1', device='cpu', backend='torch', strict_encoding=True, max_length=8192, head_length=512, batch_size=32, compile_model=False, bend_postprocess=False)
lock = threading.Lock()
stats = {'predict_requests': 0, 'requested_rows': 0, 'inferred_rows': 0, 'engine_predict_calls': 0, 'max_group_size': 0}
MAX_PADDED_TOKEN_CELLS = 32 * 1024 ** 2


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass

    def send(self, value, status=200):
        body = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(status); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(body))); self.send_header('Cache-Control', 'no-store'); self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        if self.headers.get('Host') not in {'127.0.0.1:8082', 'localhost:8082'}:
            self.send({'error': 'invalid host'}, 400); return
        self.send({'status': 'ok', 'model': 'Julia-1', 'device': 'cpu', 'strict_encoding': True, 'stats': dict(stats)}) if self.path == '/health' else self.send({'error': 'not found'}, 404)

    def do_POST(self):
        try:
            if self.headers.get('Host') not in {'127.0.0.1:8082', 'localhost:8082'} or self.headers.get('X-Persona-Lab') != 'demo-v1' or self.headers.get('Origin') not in {None, 'http://127.0.0.1:8787', 'http://localhost:8787'}:
                raise ValueError('invalid local request')
            if self.path != '/predict': raise ValueError('unknown route')
            size = int(self.headers.get('Content-Length', 0))
            if not 0 < size <= 1048576: raise ValueError('request exceeds 1MB')
            payload = json.loads(self.rfile.read(size)); rows = payload.get('rows')
            if not isinstance(rows, list) or not 1 <= len(rows) <= 32: raise ValueError('provide 1 to 32 rows')
            identifiers = [row.get('id', str(i)) if isinstance(row, dict) else str(i) for i, row in enumerate(rows)]
            if any(not isinstance(identifier, str) or not 1 <= len(identifier) <= 128 for identifier in identifiers) or len(set(identifiers)) != len(identifiers):
                raise ValueError('invalid or duplicate row IDs')
            results, audit, valid = {}, [], []
            with lock:
                started = time.monotonic()
                stats['predict_requests'] += 1; stats['requested_rows'] += len(rows)
                for identifier, original in zip(identifiers, rows):
                    try:
                        if not isinstance(original, dict): raise ValueError('invalid choice row')
                        row = {key: value for key, value in original.items() if key != 'id'}
                        if set(row) != {'state', 'question', 'options', 'type'} or row['type'] != 'choice': raise ValueError('invalid choice row')
                        if not isinstance(row['state'], str) or not isinstance(row['question'], str) or not isinstance(row['options'], list) or not 2 <= len(row['options']) <= 20 or not all(isinstance(option, str) and option for option in row['options']): raise ValueError('invalid state/question/options')
                        info = engine.encoding_info([row])[0]
                        if info['tokens'] ** 2 > MAX_PADDED_TOKEN_CELLS: raise ValueError('row exceeds configured CPU padding resource budget; input was not truncated')
                        audit.append({'id': identifier, **info}); valid.append((identifier, row, info['tokens']))
                    except (ValueError, TypeError, KeyError) as error:
                        results[identifier] = {'id': identifier, 'error': str(error)[:500], 'type': type(error).__name__}
                # Bound padding work as well as item count. This is a workload cap,
                # not a measured promise of total device RAM usage.
                groups, group, longest = [], [], 0
                for item in sorted(valid, key=lambda item: item[2]):
                    length = max(longest, item[2])
                    if group and (len(group) + 1) * length ** 2 > MAX_PADDED_TOKEN_CELLS:
                        groups.append(group); group = []; longest = 0
                    group.append(item); longest = max(longest, item[2])
                if group: groups.append(group)
                for group in groups:
                    try:
                        stats['engine_predict_calls'] += 1
                        answers = engine.predict([item[1] for item in group], probabilities=False)
                        if len(answers) != len(group): raise ValueError('model answer count mismatch')
                        stats['inferred_rows'] += len(group); stats['max_group_size'] = max(stats['max_group_size'], len(group))
                        for item, answer in zip(group, answers): results[item[0]] = {'id': item[0], **answer}
                    except (ValueError, TypeError, KeyError, OSError, RuntimeError, FloatingPointError) as error:
                        for item in group: results[item[0]] = {'id': item[0], 'error': str(error)[:500], 'type': type(error).__name__}
                elapsed = time.monotonic() - started
                peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            self.send({'results': [results[identifier] for identifier in identifiers], 'encoding': audit, 'score_semantics': 'finite_choice_argmax_not_behavior_probability', 'metrics': {'elapsed_seconds': elapsed, 'peak_rss_mib': peak / (1024 * 1024 if sys.platform == 'darwin' else 1024), 'device': 'cpu', 'inference_group_sizes': [len(group) for group in groups]}})
        except (ValueError, TypeError, KeyError, OSError, RuntimeError) as error:
            self.send({'error': str(error)[:700], 'type': type(error).__name__}, 400)


print('Julia-1 CPU service: http://127.0.0.1:8082', flush=True)
ThreadingHTTPServer(('127.0.0.1', 8082), Handler).serve_forever()
