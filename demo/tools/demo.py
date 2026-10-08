"""Start/stop only this launcher's verified project processes; no installs."""
import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

root = Path(__file__).resolve().parents[1]
state = root / 'runs/services'
qwen_binary = root / 'tools/llama/llama-b11429/llama-server'
qwen_model = root / 'models/Qwen3-0.6B-Q8_0.gguf'
julia_python = root / '.venv-julia/bin/python'
services = {
    'qwen': {'port': 8081, 'marker': str(qwen_binary), 'ready': qwen_binary.is_file() and qwen_model.is_file(), 'command': [str(qwen_binary), '--model', str(qwen_model), '--alias', 'qwen3-0.6b-q8_0', '--host', '127.0.0.1', '--port', '8081', '--ctx-size', '4096', '--threads', '4', '--n-gpu-layers', '0', '--jinja', '--no-webui', '--cors-origins', 'http://127.0.0.1:8787']},
    'julia': {'port': 8082, 'marker': str(root / 'tools/julia_server.py'), 'ready': julia_python.is_file() and (root / 'models/Julia-1/model.safetensors').is_file(), 'command': [str(julia_python), str(root / 'tools/julia_server.py')]},
    'app': {'port': 8787, 'marker': str(root / 'tools/app_server.py'), 'ready': True, 'command': [str(root / '.venv-data/bin/python') if (root / '.venv-data/bin/python').is_file() else sys.executable, str(root / 'tools/app_server.py')]},
}

def managed_pid(name):
    path = state / (name + '.json')
    if not path.exists(): return None
    record = json.loads(path.read_text())
    if record.get('marker') != services[name]['marker']: return None
    pid = record.get('pid')
    if type(pid) is not int or pid <= 1: return None
    command = subprocess.run(['ps', '-p', str(pid), '-o', 'command='], capture_output=True, text=True).stdout.strip()
    return pid if record['marker'] in command else None

def listening(port):
    with socket.socket() as client:
        client.settimeout(.2)
        return client.connect_ex(('127.0.0.1', port)) == 0

def healthy(name):
    path = '/api/packs' if name == 'app' else '/health'
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{services[name]['port']}{path}", timeout=1) as response:
            return response.status == 200
    except OSError: return False

def stop_one(name):
    pid = managed_pid(name)
    if pid:
        os.kill(pid, signal.SIGTERM)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and managed_pid(name): time.sleep(.1)
        if managed_pid(name): os.kill(pid, signal.SIGKILL)
        print(f'{name}: 프로젝트 관리 프로세스 종료 ({pid})')
    elif listening(services[name]['port']):
        print(f"{name}: 포트 {services[name]['port']}는 이 실행기가 관리하지 않습니다. 해당 프로세스를 종료하지 않았습니다.")
    (state / (name + '.json')).unlink(missing_ok=True)

def start():
    state.mkdir(parents=True, exist_ok=True)
    # Inspect all ports before spawning anything; never kill an unknown owner.
    for name, item in services.items():
        if listening(item['port']) and not managed_pid(name):
            raise RuntimeError(f"포트 {item['port']} 충돌 ({name}). 해당 프로세스를 확인해 종료하거나 기존 서비스를 사용하세요. 이 실행기는 임의 프로세스를 종료하지 않습니다.")
    launched = []
    try:
        for name, item in services.items():
            if not item['ready']:
                print(f'{name}: 모델/런타임 미준비. Mock으로 앱을 사용할 수 있습니다. 준비 절차는 docs/MODEL.md 참고.'); continue
            if managed_pid(name):
                print(f'{name}: 이미 관리 중'); continue
            log_path = state / (name + '.log')
            with log_path.open('ab') as log:
                process = subprocess.Popen(item['command'], cwd=root, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
            (state / (name + '.json')).write_text(json.dumps({'pid': process.pid, 'marker': item['marker']}))
            launched.append(name)
            deadline = time.monotonic() + 40
            while time.monotonic() < deadline:
                if healthy(name): break
                if process.poll() is not None: raise RuntimeError(f'{name}: 시작 실패. 로그: {log_path}')
                time.sleep(.2)
            else: raise RuntimeError(f'{name}: 40초 내 준비되지 않음. 로그: {log_path}')
            print(f'{name}: 준비됨 (PID {process.pid}, 127.0.0.1:{item["port"]})', flush=True)
    except Exception:
        for name in reversed(launched): stop_one(name)
        raise
    print('데모: http://127.0.0.1:8787 · IAB에서 열기 · 종료: sh tools/demo.sh stop')

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('action', choices=['start', 'stop', 'status'])
args = parser.parse_args()
try:
    if args.action == 'start': start()
    elif args.action == 'stop':
        for name in ('app', 'julia', 'qwen'): stop_one(name)
    else:
        for name, item in services.items():
            print(json.dumps({'service': name, 'prepared': item['ready'], 'managed_pid': managed_pid(name), 'port': item['port'], 'listening': listening(item['port']), 'healthy': healthy(name)}, ensure_ascii=False))
except (OSError, ValueError, RuntimeError) as error:
    print(str(error), file=sys.stderr); sys.exit(1)
