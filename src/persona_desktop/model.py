"""Only start and stop this application's bundled, loopback inference process."""
import hashlib
import json
import socket
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

from persona_lab.contracts import require

class BundledModel:
    def __init__(self, assets: Path, home: Path, info=None):
        self.assets, self.home = assets, home
        self.info = info if info is not None else json.loads((assets/'model.json').read_text())
        self.process = None
        self.port = None
        self.phase, self.error = 'starting', None
        self.lock = threading.Lock()
        self.stopped = threading.Event()
        self.log = None

    def start(self, origin):
        self.origin = origin
        threading.Thread(target=self._start, name='bundled-model', daemon=True).start()

    def _start(self):
        try:
            model = self.assets/'models'/self.info['file']
            sha = hashlib.sha256()
            with model.open('rb') as stream:
                for block in iter(lambda: stream.read(1024*1024), b''): sha.update(block)
            require(sha.hexdigest() == self.info['sha256'], '기본 모델 파일이 변경되었습니다.')
            if self.stopped.is_set(): return
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0)); self.port = sock.getsockname()[1]
            command = [str(self.assets/'runtime/llama-server'), '--model', str(model), '--alias', self.info['model_id'], '--host','127.0.0.1','--port',str(self.port),'--ctx-size',str(self.info.get('context_size',8192)),'--threads','4','--n-gpu-layers',str(self.info.get('gpu_layers',0)),'--jinja','--no-webui','--cors-origins',self.origin]
            if self.info.get('endpoint')=='/v1/systemone':
                command+=['--batch-size',str(self.info.get('batch_size',8192)),'--ubatch-size',str(self.info.get('ubatch_size',8192))]
            if 'parallel' in self.info:command+=['--parallel',str(self.info['parallel'])]
            self.log = (self.home/'model.log').open('ab')
            with self.lock:
                if self.stopped.is_set(): return
                self.process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=self.log, stderr=self.log)
            deadline = time.monotonic()+60
            while not self.stopped.wait(.25) and time.monotonic() < deadline:
                require(self.process.poll() is None, '기본 모델을 시작하지 못했습니다. 모델 로그를 확인하세요.')
                try:
                    with urllib.request.urlopen(f'http://127.0.0.1:{self.port}/health', timeout=1) as response:
                        if response.status == 200:
                            self.phase, self.error = 'ready', None
                            return
                except OSError: pass
            if not self.stopped.is_set(): raise ValueError('모델 준비 시간이 초과되었습니다.')
        except (OSError, ValueError) as error:
            self.phase, self.error = 'failed', str(error)
            self._stop_process()
        finally:
            if self.stopped.is_set():
                self._stop_process()
                self.phase = 'stopped'

    def status(self):
        if self.phase == 'ready' and (not self.process or self.process.poll() is not None):
            self.phase, self.error = 'failed', '모델이 종료되었습니다. 다시 불러오세요.'
        return {'phase': self.phase, 'error': self.error, 'info': self.info}

    def backend(self, structured=False, response=False, linked=False, finite=False, survey=False, survey_version=None):
        finite=finite or survey or survey_version is not None
        require(finite, '이전 모델은 제거되었습니다. 저장된 결과는 열람하거나 복사할 수 있지만 이전 실행은 재개할 수 없습니다.')
        require(self.status()['phase'] == 'ready', self.error or '모델을 불러오는 중입니다.')
        from persona_lab.finite_decision import ClefBackend
        require(self.info.get('endpoint')=='/v1/systemone' and self.info.get('model_architecture')=='clef', '전용 결정 모델이 준비되지 않았습니다.')
        return ClefBackend(endpoint=f'http://127.0.0.1:{self.port}',model_id=self.info['model_id'],revision=self.info['sha256'],runtime_revision=self.info['runtime'],context_tokens=self.info.get('context_size',8192),survey=survey,survey_version=survey_version)

    def _stop_process(self):
        with self.lock:
            if self.process and self.process.poll() is None:
                self.process.terminate()
                try: self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill(); self.process.wait(timeout=5)
            if self.log: self.log.close(); self.log = None

    def close(self):
        self.stopped.set()
        self._stop_process()
