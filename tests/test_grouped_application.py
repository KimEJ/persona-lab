"""New grouped dispatch and shared traces preserve frozen older executions."""
import copy
import json
import sqlite3
import unittest
from unittest.mock import Mock, patch

import test_sampling_flow as fixtures
from persona_desktop.application import Application, atomic_json
from persona_desktop.model import BundledModel
from persona_lab.backends import FixtureBackend
from persona_lab.contracts import ContractError
from persona_lab.responses import SURVEY_SCENARIO_ID, SURVEY_V2_SCENARIO_ID, SURVEY_V3_SCENARIO_ID, SURVEY_V4_SCENARIO_ID
from persona_lab.runner import run
from persona_lab.survey import SURVEY_V3_DOMAINS, SURVEY_V3_QUESTIONS, SURVEY_V4_DOMAINS, SURVEY_V4_QUESTIONS


class GroupedApplicationTests(unittest.TestCase):
    setUp = fixtures.SamplingFlowTests.setUp
    write_pack = fixtures.SamplingFlowTests.write_pack
    finish = fixtures.SamplingFlowTests.finish

    def configure(self, count=1, items=1, repeats=1, workflow=None):
        draft = fixtures.SamplingFlowTests.configure(self, self.app.create(), count, items, repeats)
        for item in draft['items']:
            item['valuation'] = {'mode': 'manual', 'currency': 'JPY', 'billing': 'one_time',
                                 'boundaries': ['500', '1500', '3000']}
        saved = self.app.save(draft['id'], draft)
        # Author a frozen legacy manifest after editable drafts migrate to v4.
        if workflow:
            saved['workflow'] = workflow
        return saved

    def install_model(self, backend=None):
        model = Mock()
        model.backend.return_value = backend or FixtureBackend()
        self.app.test_backend = None
        self.app.model = model
        return model

    @staticmethod
    def dedicated_backend(corrected=True):
        backend = FixtureBackend()
        backend.kind = 'dedicated_local_decision'
        backend.inference_protocol = 'survey-grouped-v1'
        backend.backend_id = ('llama-cpp:clef:model-sha:pinned-runtime'
                              + ('+metal-fusion-off-v1' if corrected else '')
                              + ':survey-grouped-v1')
        return backend

    def freeze(self, draft, filename='run.json', **extra):
        spec = self.app.make_spec(draft)
        snapshot = {'draft': {key: value for key, value in draft.items()
                             if key not in {'run', 'legacy_items', 'question_catalog'}},
                    'spec': spec, 'source': self.app.source, 'created_at': 'frozen-test-time', **extra}
        directory = self.app.directory(draft['id'])
        atomic_json(directory / filename, snapshot)
        return directory, spec

    def test_new_specs_keep_nine_measurements_and_version_grouped_inference(self):
        draft = self.configure()
        spec = self.app.make_spec(draft)
        self.assertEqual((spec['inference_protocol'], spec['batch_size']), ('survey-staged-v1', 7))
        self.assertEqual(spec['scenario']['id'], SURVEY_V4_SCENARIO_ID)
        self.assertEqual(tuple(question['domain'] for question in spec['questions']), SURVEY_V4_DOMAINS)
        previous = copy.deepcopy(draft)
        previous['workflow'] = SURVEY_V3_SCENARIO_ID
        preserved = self.app.make_spec(previous)
        self.assertEqual((preserved['inference_protocol'], preserved['batch_size']), ('survey-grouped-v2', 9))
        self.assertEqual(tuple(question['domain'] for question in preserved['questions']), SURVEY_V3_DOMAINS)
        older = copy.deepcopy(draft)
        older['workflow'] = SURVEY_SCENARIO_ID
        spec = self.app.make_spec(older)
        self.assertNotIn('inference_protocol', spec)
        self.assertEqual((spec['batch_size'], len(spec['questions'])), (1, 8))

    def test_editable_old_draft_upgrades_but_frozen_v3_and_its_resume_catalog_stay_original(self):
        draft = self.configure(workflow=SURVEY_V3_SCENARIO_ID)
        editable = {key: value for key, value in draft.items()
                    if key not in {'run', 'legacy_items', 'question_catalog'}}
        directory = self.app.directory(draft['id'])
        atomic_json(directory / 'draft.json', editable)
        self.assertEqual(self.app.get(draft['id'])['workflow'], SURVEY_V4_SCENARIO_ID)
        self.freeze(draft)
        before = (directory / 'run.json').read_bytes()
        model = self.install_model()
        self.app.start(draft['id'])
        self.assertEqual(self.finish(draft['id'])['backend_errors'], 0)
        flags = model.backend.call_args.kwargs
        self.assertEqual((flags['survey_version'], flags['inference_protocol']),
                         (SURVEY_V3_SCENARIO_ID, 'survey-grouped-v2'))
        self.assertEqual(flags['survey_questions'], SURVEY_V3_QUESTIONS)
        self.assertEqual((directory / 'run.json').read_bytes(), before)
        self.assertEqual(self.app.get(draft['id'])['workflow'], SURVEY_V3_SCENARIO_ID)
        self.assertEqual(self.app.create(draft['id'])['workflow'], SURVEY_V4_SCENARIO_ID)

    def test_new_start_passes_frozen_catalog_and_grouped_preflight(self):
        checked = []

        class Probe(FixtureBackend):
            inference_protocol = 'survey-staged-v1'
            batch_limit = 7

            def preflight_batch(inner, batch):
                checked.append(batch)

            def preflight(inner, job):
                pass

        draft = self.configure(count=2, items=2, repeats=2)
        model = self.install_model(Probe())
        self.app.start(draft['id'])
        status = self.finish(draft['id'])
        self.assertEqual((status['cursor'], status['total'], status['backend_errors']), (72, 72, 0))
        flags = model.backend.call_args.kwargs
        self.assertEqual(flags['inference_protocol'], 'survey-staged-v1')
        self.assertEqual(flags['survey_questions'], self.app.snapshot(draft['id'])['spec']['questions'])
        self.assertEqual(flags['survey_version'], SURVEY_V4_SCENARIO_ID)
        self.assertTrue(checked)
        for batch in checked:
            self.assertEqual(len(batch), 7)
            self.assertEqual({(job.persona.persona_id, job.product['id'], job.repeat) for job in batch},
                             {(batch[0].persona.persona_id, batch[0].product['id'], 0)})

    def test_old_run_and_preparation_without_marker_keep_singleton_dispatch(self):
        model = self.install_model()
        for filename in ('run.json', 'preparation.json'):
            with self.subTest(filename=filename):
                draft = self.configure(workflow=SURVEY_V2_SCENARIO_ID)
                spec = self.app.make_spec(draft)
                spec.pop('inference_protocol')
                spec['batch_size'] = 8
                snapshot = {'draft': {key: value for key, value in draft.items()
                                     if key not in {'run', 'legacy_items', 'question_catalog'}},
                            'spec': spec, 'source': self.app.source, 'created_at': 'frozen-test-time'}
                directory = self.app.directory(draft['id'])
                atomic_json(directory / filename, snapshot)
                frozen = (directory / filename).read_bytes()
                self.app.start(draft['id'])
                status = self.finish(draft['id'])
                self.assertEqual((status['cursor'], status['backend_errors']), (10, 0))
                flags = model.backend.call_args.kwargs
                self.assertIsNone(flags['inference_protocol'])
                self.assertIsNone(flags['survey_questions'])
                self.assertEqual((directory / 'run.json').read_bytes(), frozen)
                self.assertEqual(self.app.snapshot(draft['id']), snapshot)

    def test_bundled_model_passes_grouped_protocol_and_frozen_questions(self):
        model = BundledModel(self.root / 'assets', self.home, info={
            'model_id': 'clef', 'sha256': 'model-sha', 'runtime': 'pinned-runtime',
            'endpoint': '/v1/systemone', 'model_architecture': 'clef'})
        model.port = 32000
        model.phase = 'ready'
        model.process = Mock()
        model.process.poll.return_value = None
        questions = copy.deepcopy(SURVEY_V4_QUESTIONS)
        with patch('persona_lab.finite_decision.ClefBackend') as clef:
            result = model.backend(survey_version=SURVEY_V4_SCENARIO_ID,
                                   inference_protocol='survey-staged-v1', survey_questions=questions)
        self.assertIs(result, clef.return_value)
        self.assertEqual(clef.call_args.kwargs['inference_protocol'], 'survey-staged-v1')
        self.assertEqual(clef.call_args.kwargs['survey_questions'], questions)

    def test_uncorrected_run_is_rejected_before_worker_or_record_changes(self):
        draft = self.configure(count=2, workflow=SURVEY_V2_SCENARIO_ID)
        directory, spec = self.freeze(draft)
        store = directory / 'run.sqlite'
        partial = run(self.app.data_path, self.app.source, spec, store,
                      self.dedicated_backend(corrected=False), max_batches=1)
        self.assertEqual((partial['cursor'], partial['total']), (10, 20))
        preserved = {path: path.read_bytes() for path in (directory / 'run.json', store)}
        self.install_model(self.dedicated_backend())
        with patch('persona_desktop.application.preflight_jobs') as preflight, \
                patch('persona_desktop.application.run') as execute:
            with self.assertRaisesRegex(ContractError, '추론 런타임이 변경.*복제'):
                self.app.start(draft['id'])
            preflight.assert_not_called()
            execute.assert_not_called()
        self.assertNotIn(draft['id'], self.app.workers)
        self.assertFalse((directory / 'error.txt').exists())
        for path, content in preserved.items():
            self.assertEqual(path.read_bytes(), content)

    def test_uncorrected_preparation_is_rejected_before_preflight_or_promotion(self):
        draft = self.configure(workflow=SURVEY_V2_SCENARIO_ID)
        draft['items'][0]['valuation'].update(mode='auto', boundaries=['', '', ''])
        draft = self.app.save(draft['id'], draft)
        draft['workflow'] = SURVEY_V2_SCENARIO_ID
        directory, _ = self.freeze(draft, 'preparation.json', price_calibration={
            'backend_id': self.dedicated_backend(corrected=False).backend_id,
            'completed': 1, 'total': 12, 'products': {}})
        preserved = {path: path.read_bytes() for path in (directory / 'draft.json', directory / 'preparation.json')}
        self.install_model(self.dedicated_backend())
        with patch('persona_desktop.application.preflight_jobs') as preflight, \
                patch('persona_desktop.application.calibrate') as calibrate:
            with self.assertRaisesRegex(ContractError, '추론 런타임이 변경.*복제'):
                self.app.start(draft['id'])
            preflight.assert_not_called()
            calibrate.assert_not_called()
        self.assertNotIn(draft['id'], self.app.workers)
        self.assertFalse((directory / 'run.json').exists())
        self.assertFalse((directory / 'run.sqlite').exists())
        self.assertFalse((directory / 'error.txt').exists())
        for path, content in preserved.items():
            self.assertEqual(path.read_bytes(), content)

    def test_same_corrected_runtime_resumes_with_existing_choices_and_fingerprint(self):
        draft = self.configure(count=2, workflow=SURVEY_V2_SCENARIO_ID)
        directory, spec = self.freeze(draft)
        store = directory / 'run.sqlite'
        backend = self.dedicated_backend()
        partial = run(self.app.data_path, self.app.source, spec, store, backend, max_batches=1)
        self.assertEqual((partial['cursor'], partial['total']), (10, 20))
        manifest = (directory / 'run.json').read_bytes()
        with sqlite3.connect(store) as db:
            fingerprint = db.execute('SELECT fingerprint FROM run').fetchone()[0]
            records = db.execute('SELECT ordinal,payload FROM results ORDER BY ordinal').fetchall()
        self.install_model(self.dedicated_backend())
        self.app.start(draft['id'])
        status = self.finish(draft['id'])
        self.assertEqual((status['cursor'], status['total'], status['backend_errors']), (20, 20, 0))
        self.assertEqual((directory / 'run.json').read_bytes(), manifest)
        with sqlite3.connect(store) as db:
            self.assertEqual(db.execute('SELECT fingerprint FROM run').fetchone()[0], fingerprint)
            self.assertEqual(db.execute('SELECT ordinal,payload FROM results ORDER BY ordinal LIMIT 10').fetchall(), records)

    def test_detail_returns_one_shared_call_and_legacy_rows_after_mapping_added(self):
        with sqlite3.connect(':memory:') as db:
            db.execute('CREATE TABLE model_calls (id INTEGER PRIMARY KEY,job_id TEXT,started_at TEXT,request TEXT,response TEXT,error TEXT,finished_at TEXT)')
            db.execute('INSERT INTO model_calls VALUES (1,?,?,?,?,?,?)',
                       ('first-job', 'start', '{"questions":8}', '{"answers":8}', None, 'finish'))
            db.execute('INSERT INTO model_calls VALUES (2,?,?,?,?,?,?)',
                       ('old-job', 'start', '{"questions":1}', '{"answers":1}', None, 'finish'))
            self.assertEqual([call['id'] for call in Application.model_calls(self.home, 'old-job', db)], [2])
            db.execute('CREATE TABLE model_call_jobs (call_id INTEGER NOT NULL,job_id TEXT NOT NULL,PRIMARY KEY(call_id,job_id))')
            db.executemany('INSERT INTO model_call_jobs VALUES (1,?)', [(f'job-{index}',) for index in range(8)])
            db.execute('INSERT INTO model_call_jobs VALUES (1,?)', ('first-job',))
            for job in ('first-job', 'job-0', 'job-7'):
                calls = Application.model_calls(self.home, job, db)
                self.assertEqual([call['id'] for call in calls], [1])
                self.assertEqual(json.loads(calls[0]['request']), {'questions': 8})
            self.assertEqual([call['id'] for call in Application.model_calls(self.home, 'old-job', db)], [2])
            self.assertEqual([call['id'] for call in Application.model_calls(self.home, db=db)], [1, 2])


if __name__ == '__main__':
    unittest.main()
