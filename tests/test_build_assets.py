"""The default bundle must never collect old weights from the source cache."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

spec=importlib.util.spec_from_file_location('persona_build',Path(__file__).resolve().parents[1]/'tools/build.py')
build=importlib.util.module_from_spec(spec);spec.loader.exec_module(build)

class BuildAssetsTests(unittest.TestCase):
    def test_only_current_weight_is_copied_without_legacy_weights(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/'assets';destination=root/'bundle-assets'
            (source/'models').mkdir(parents=True)
            (source/'model.json').write_text(json.dumps({'file':'current.gguf'}))
            (source/'legacy-model.json').write_text(json.dumps({'file':'absent-old.gguf'}))
            (source/'models/current.gguf').write_bytes(b'current')
            (source/'models/unused.gguf').write_bytes(b'old')
            (source/'data').mkdir();(source/'data/source.json').write_text('{}')
            build.copy_assets(source,destination)
            self.assertEqual([p.name for p in (destination/'models').iterdir()],['current.gguf'])
            self.assertEqual((destination/'models/current.gguf').read_bytes(),b'current')
            self.assertTrue((destination/'data/source.json').is_file())

if __name__=='__main__':unittest.main()
