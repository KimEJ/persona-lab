import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from persona_desktop.model import BundledModel
from persona_lab.contracts import ContractError
from persona_lab.responses import SURVEY_V2_SCENARIO_ID


class ModelDispatchTests(unittest.TestCase):
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
