import signal
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from persona_desktop.model import BundledModel
from persona_desktop.server import main


class ShutdownTests(unittest.TestCase):
    def test_close_terminates_the_model_child_and_closes_its_log(self):
        with tempfile.TemporaryDirectory() as temporary:
            home=Path(temporary)
            model=BundledModel(home,home,info={})
            model.log=(home/'model.log').open('ab')
            log=model.log
            child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'],stdin=subprocess.DEVNULL,stdout=log,stderr=log)
            model.process=child
            try:
                model.close()
                self.assertIsNotNone(child.poll())
                self.assertTrue(log.closed)
                self.assertTrue(model.stopped.is_set())
                model.close()
            finally:
                if child.poll() is None:child.kill();child.wait(timeout=5)

    def test_close_during_model_validation_prevents_a_late_child(self):
        with tempfile.TemporaryDirectory() as temporary:
            home=Path(temporary)
            (home/'models').mkdir()
            (home/'models/test.gguf').write_bytes(b'test')
            model=BundledModel(home,home,info={'file':'test.gguf','sha256':'test-hash'})
            validating,release=threading.Event(),threading.Event()
            def update(_):
                validating.set()
                if not release.wait(5):raise OSError('validation test timed out')
            digest=SimpleNamespace(update=update,hexdigest=lambda:'test-hash')
            thread=threading.Thread(target=model._start)
            with patch('persona_desktop.model.hashlib.sha256',return_value=digest), patch('persona_desktop.model.subprocess.Popen') as spawn:
                thread.start()
                try:
                    self.assertTrue(validating.wait(5))
                    model.close()
                finally:
                    release.set();thread.join(timeout=5)
                self.assertFalse(thread.is_alive())
                spawn.assert_not_called()
                self.assertEqual(model.phase,'stopped')

    def test_server_installs_shutdown_handlers_before_model_start_and_cleans_up_a_start_failure(self):
        app=Mock()
        server=Mock(server_address=('127.0.0.1',32000))
        handlers={}
        def start(_):
            self.assertEqual(set(handlers),{signal.SIGTERM,signal.SIGINT})
            raise RuntimeError('model startup failed')
        app.model.start.side_effect=start
        with patch('persona_desktop.server.Application',return_value=app), patch('persona_desktop.server.make_server',return_value=server), patch('persona_desktop.server.signal.signal',side_effect=lambda kind,handler:handlers.__setitem__(kind,handler)), patch.object(sys,'argv',['server','--root','/tmp/root','--home','/tmp/home']):
            with self.assertRaisesRegex(RuntimeError,'model startup failed'):main()
        server.server_close.assert_called_once()
        app.close.assert_called_once()
        server.serve_forever.assert_not_called()


if __name__=='__main__':unittest.main()
