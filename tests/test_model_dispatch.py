import json
import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from persona_desktop.model import BundledModel
from persona_lab.contracts import ContractError
from persona_lab.responses import SURVEY_V2_SCENARIO_ID


class ModelDispatchTests(unittest.TestCase):
    def test_corrected_metal_policy_starts_child_with_fusion_disabled(self):
        with tempfile.TemporaryDirectory() as temporary:
            assets=Path(temporary);(assets/'models').mkdir()
            data=b'model fixture';(assets/'models/test.gguf').write_bytes(data)
            info={'model_id':'clef','file':'test.gguf','sha256':hashlib.sha256(data).hexdigest(),
                  'runtime':'llama.cpp b11429','endpoint':'/v1/systemone','model_architecture':'clef',
                  'gpu_layers':99,'parallel':1,'runtime_policy':'metal-fusion-off-v1'}
            model=BundledModel(assets,assets,info=info);model.origin='http://127.0.0.1:32000'
            self.addCleanup(model.close)
            process=Mock();process.poll.return_value=None
            with patch.dict(os.environ,{'GGML_METAL_FUSION_DISABLE':'0'}), \
                 patch('persona_desktop.model.socket.socket') as socket, \
                 patch('persona_desktop.model.subprocess.Popen',return_value=process) as spawn, \
                 patch('persona_desktop.model.urllib.request.urlopen') as health:
                socket.return_value.__enter__.return_value.getsockname.return_value=('127.0.0.1',32000)
                health.return_value.__enter__.return_value.status=200
                model._start()
                self.assertEqual(model.phase,'ready')
                self.assertEqual(spawn.call_args.kwargs['env']['GGML_METAL_FUSION_DISABLE'],'1')
                self.assertEqual(os.environ['GGML_METAL_FUSION_DISABLE'],'0')
                command=spawn.call_args.args[0]
                self.assertEqual(command[command.index('--n-gpu-layers')+1],'99')

    def test_corrected_runtime_fingerprint_cannot_match_previous_metal_results(self):
        with tempfile.TemporaryDirectory() as temporary:
            assets=Path(temporary)
            info={'model_id':'clef','sha256':'model-sha','runtime':'llama.cpp b11429',
                  'endpoint':'/v1/systemone','model_architecture':'clef'}
            model=BundledModel(assets,assets,info=info)
            model.port=32000;model.phase='ready';model.process=SimpleNamespace(poll=lambda:None)
            original=model.backend(survey_version=SURVEY_V2_SCENARIO_ID).backend_id
            model.info={**info,'runtime_policy':'metal-fusion-off-v1'}
            corrected=model.backend(survey_version=SURVEY_V2_SCENARIO_ID).backend_id
            self.assertNotEqual(original,corrected)
            self.assertIn('llama.cpp b11429+metal-fusion-off-v1',corrected)
            model.info={**info,'runtime_policy':'unsupported'}
            with self.assertRaisesRegex(ContractError,'런타임 설정'):
                model.backend(survey_version=SURVEY_V2_SCENARIO_ID)

    def test_finite_versions_keep_the_clef_backend_and_require_the_head(self):
        with tempfile.TemporaryDirectory() as temporary:
            assets=Path(temporary)
            clef={'model_id':'clef','sha256':'clef-sha','runtime':'llama.cpp pinned','endpoint':'/v1/systemone','model_architecture':'clef'}
            (assets/'model.json').write_text(json.dumps(clef))
            model=BundledModel(assets,assets)
            model.port=32000;model.phase='ready';model.process=SimpleNamespace(poll=lambda:None)
            for flags,suffix,survey,version in [
                ({'finite':True},'finite-choice-v1',False,None),
                ({'survey':True},'survey-choice-v1',True,None),
                ({'survey_version':SURVEY_V2_SCENARIO_ID},'survey-choice-v2',False,SURVEY_V2_SCENARIO_ID),
            ]:
                with self.subTest(version=suffix):
                    backend=model.backend(**flags)
                    self.assertEqual(backend.kind,'dedicated_local_decision')
                    self.assertEqual(backend.backend_id,f'llama-cpp:clef:clef-sha:llama.cpp pinned:{suffix}')
                    self.assertEqual(backend.endpoint,'http://127.0.0.1:32000')
                    self.assertEqual((backend.survey,backend.survey_version),(survey,version))
            model.info={**clef,'model_architecture':'qwen'}
            with self.assertRaisesRegex(ContractError,'전용 결정 모델'):
                model.backend(finite=True)

    def test_old_generative_runs_fail_without_starting_or_downloading_a_model(self):
        with tempfile.TemporaryDirectory() as temporary:
            assets=Path(temporary)
            (assets/'model.json').write_text(json.dumps({'model_id':'clef','sha256':'clef-sha'}))
            for name in ('generative-model.json','legacy-model.json'):
                (assets/name).write_text(json.dumps({'model_id':'old-qwen','sha256':'old-sha'}))
            model=BundledModel(assets,assets)
            with patch.object(BundledModel,'start') as start, patch('persona_desktop.model.subprocess.Popen') as spawn, patch('persona_desktop.model.urllib.request.urlopen') as network:
                for flags in ({},{'structured':True},{'response':True},{'linked':True}):
                    with self.subTest(flags=flags), self.assertRaisesRegex(ContractError,'이전 모델은 제거되었습니다.*열람하거나 복사.*재개할 수 없습니다'):
                        model.backend(**flags)
                start.assert_not_called();spawn.assert_not_called();network.assert_not_called()


if __name__=='__main__':unittest.main()
