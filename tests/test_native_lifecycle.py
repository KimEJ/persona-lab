"""Run the real AppKit close action with a small service and no model inference."""
import json
import os
import plistlib
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SERVICE = '''
import json, os, signal, subprocess, threading, time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
home = Path(os.environ['PERSONA_LAB_HOME'])
stopped = threading.Event()
signal.signal(signal.SIGTERM, lambda *_: stopped.set())
child = subprocess.Popen(['/bin/sleep', '60'])
home.joinpath('worker.json').write_text(json.dumps({'worker': os.getpid(), 'model': child.pid}))
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def do_GET(self):
        body = b"""<script>window.appCommands={prepareQuit:async()=>{
            await fetch('/save',{method:'POST'});
            window.webkit.messageHandlers.native.postMessage({kind:'quitReady'});
        }};</script>"""
        self.send_response(200); self.end_headers(); self.wfile.write(body)
    def do_POST(self):
        time.sleep(.1)
        home.joinpath('saved').write_text('saved before quit')
        self.send_response(200); self.end_headers()
server = None
try:
    if os.environ['LIFECYCLE_READY'] == '1':
        server = HTTPServer(('127.0.0.1', 0), Handler)
        server.timeout = .05
        print(json.dumps({'url': 'http://127.0.0.1:%s' % server.server_port}), flush=True)
        while not stopped.is_set(): server.handle_request()
    else: stopped.wait()
finally:
    if server: server.server_close()
    child.terminate(); child.wait(timeout=5)
    home.joinpath('stopped').write_text('service and model stopped')
'''


@unittest.skipUnless(sys.platform == 'darwin', 'requires AppKit and WebKit')
class NativeLifecycleTests(unittest.TestCase):
    def test_main_window_close_saves_and_stops_background_processes(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            contents = base / 'Lifecycle.app/Contents'
            macos = contents / 'MacOS'; macos.mkdir(parents=True)
            resources = contents / 'Resources'; resources.mkdir()
            info = plistlib.loads((ROOT / 'macos/Info.plist').read_bytes())
            (contents / 'Info.plist').write_bytes(plistlib.dumps(info))
            source = base / 'Probe.swift'
            source.write_text((ROOT / 'tests/native_lifecycle_probe.swift').read_text() + '\n' + (ROOT / 'macos/App.swift').read_text())
            executable = macos / 'PersonaLab'
            subprocess.run(['xcrun', 'swiftc', '-D', 'NATIVE_LIFECYCLE_PROBE', str(source),
                            '-o', str(executable), '-framework', 'AppKit', '-framework', 'WebKit',
                            '-target', 'arm64-apple-macos14.0', '-module-cache-path', str(base / 'module-cache')],
                           check=True, capture_output=True, text=True)
            (resources / 'service.py').write_text(SERVICE)
            runner = macos / 'PythonRunner'
            runner.write_text('#!/bin/sh\nunset PYTHONHOME PYTHONPATH\nexec ' + shlex.quote(sys.executable)
                              + ' "$(dirname "$0")/../Resources/service.py"\n')
            runner.chmod(0o755)
            for ready in (False, True):
                with self.subTest(service_ready=ready):
                    home = base / ('ready' if ready else 'starting'); home.mkdir()
                    env = {**os.environ, 'PERSONA_LAB_HOME': str(home), 'LIFECYCLE_READY': str(int(ready))}
                    process = subprocess.Popen([str(executable)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                    try:
                        _, stderr = process.communicate(timeout=20)
                        self.assertEqual(process.returncode, 0, stderr.decode(errors='replace'))
                        self.assertTrue((home / 'stopped').exists(), 'service did not finish cleanup')
                        self.assertEqual((home / 'saved').exists(), ready, 'ready editor must finish saving')
                        pids = json.loads((home / 'worker.json').read_text())
                        for kind, pid in pids.items():
                            with self.assertRaises(ProcessLookupError, msg=f'{kind} is still running'):
                                os.kill(pid, 0)
                    finally:
                        if process.poll() is None:
                            process.kill(); process.wait()
                        if (home / 'worker.json').exists():
                            for pid in json.loads((home / 'worker.json').read_text()).values():
                                try: os.kill(pid, 15)
                                except ProcessLookupError: pass


if __name__ == '__main__': unittest.main()
