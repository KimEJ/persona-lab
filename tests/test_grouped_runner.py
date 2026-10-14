"""Grouped request journals and checkpoints retain all questionnaire cells."""
import copy
import io
import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from http.client import HTTPException
from unittest.mock import patch

from persona_lab.contracts import ContractError, validate_experiment
from persona_lab.finite_decision import ClefBackend
from persona_lab.responses import SURVEY_V2_SCENARIO_ID
from persona_lab.runner import jobs, preflight_jobs, run
from persona_lab.survey import SURVEY_V2_QUESTIONS
import test_survey_v2 as fixtures


class GroupedRunnerTests(unittest.TestCase):
    setUp = fixtures.SurveyV2Tests.setUp
    spec = fixtures.SurveyV2Tests.spec

    def configure(self, count=1):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path, self.store = Path(temporary.name) / 'people.jsonl', Path(temporary.name) / 'run.sqlite'
        rows = [{**self.job.persona.raw, 'uuid': 'uuid-secret' if index == 0 else f'uuid-{index}'}
                for index in range(count)]
        self.path.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows))
        self.source = {'schema_version': '0.1', 'source_id': 'grouped-test', 'version': 'authored-v1',
                       'url': 'local:test', 'license_id': 'LicenseRef-Test', 'license_url': 'local:test',
                       'origin': 'project_synthetic_fixture'}
        self.experiment = {**self.spec(), 'inference_protocol': 'survey-grouped-v1', 'batch_size': 10}
        self.experiment['panel'].update(sample_size=count, selected_uuids=[row['uuid'] for row in rows])
        self.grouped = ClefBackend(survey_version=SURVEY_V2_SCENARIO_ID,
                                  inference_protocol='survey-grouped-v1',
                                  survey_questions=copy.deepcopy(SURVEY_V2_QUESTIONS))
        self.bodies = []

    def reply(self, request, **kwargs):
        if request.full_url.endswith('/tokenize'):
            return io.BytesIO(json.dumps({'tokens': [1] * 2000}).encode())
        body = json.loads(request.data)
        self.bodies.append(body)
        answers = {}
        for identifier, question in body['questions'].items():
            choice = next(option for option in question['criteria'] if option != 'unknown')
            answers[identifier] = {'type': 'choice', 'choice': choice,
                                   'probabilities': {option: float(option == choice) for option in question['criteria']}}
        return io.BytesIO(json.dumps({'answers': answers, 'usage': {'input_tokens': 2000, 'output_tokens': 0}}).encode())

    def test_cancel_finishes_one_person_and_resume_keeps_its_results_and_shared_calls(self):
        self.configure(2)
        event = threading.Event()
        def reply(request, **kwargs):
            response = self.reply(request, **kwargs)
            if len(self.bodies) == 1:
                event.set()
            return response
        with patch('urllib.request.urlopen', side_effect=reply):
            partial = run(self.path, self.source, self.experiment, self.store, self.grouped, cancelled=event.is_set)
        self.assertEqual((partial['cursor'], partial['total'], partial['status']), (10, 20, 'paused'))
        self.assertEqual([len(body['questions']) for body in self.bodies], [8, 1, 1])
        with sqlite3.connect(self.store) as db:
            preserved = db.execute('SELECT payload FROM results ORDER BY ordinal').fetchall()
            self.assertEqual(db.execute('SELECT COUNT(*) FROM model_calls').fetchone()[0], 3)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM model_call_jobs').fetchone()[0], 10)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM model_call_jobs WHERE call_id=1').fetchone()[0], 8)
        with patch('urllib.request.urlopen', side_effect=self.reply):
            complete = run(self.path, self.source, self.experiment, self.store, self.grouped)
        self.assertEqual((complete['cursor'], complete['backend_errors']), (20, 0))
        with sqlite3.connect(self.store) as db:
            self.assertEqual(db.execute('SELECT payload FROM results ORDER BY ordinal LIMIT 10').fetchall(), preserved)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM model_calls').fetchone()[0], 6)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM results').fetchone()[0], 20)
        self.assertEqual(self.grouped.metrics['requests'], 6)

    def test_retry_one_failed_cell_reuses_full_schema_and_preserves_other_nine_cells(self):
        self.configure()
        failed_id = SURVEY_V2_QUESTIONS[1]['id']
        def invalid(request, **kwargs):
            response = self.reply(request, **kwargs)
            envelope = json.loads(response.getvalue())
            if failed_id in envelope.get('answers', {}):
                envelope['answers'][failed_id]['probabilities'] = {}
            return io.BytesIO(json.dumps(envelope).encode())
        with patch('urllib.request.urlopen', side_effect=invalid):
            initial = run(self.path, self.source, self.experiment, self.store, self.grouped)
        self.assertEqual((initial['cursor'], initial['backend_errors']), (10, 1))
        with sqlite3.connect(self.store) as db:
            normal = db.execute("SELECT job_id,payload FROM results WHERE status!='backend_error'").fetchall()
        with patch('urllib.request.urlopen', side_effect=self.reply):
            retried = run(self.path, self.source, self.experiment, self.store, self.grouped, retry_errors=True)
        self.assertEqual(retried['backend_errors'], 0)
        self.assertEqual(self.bodies[-1], self.bodies[0])
        self.assertEqual(len(self.bodies), 4)
        with sqlite3.connect(self.store) as db:
            for job_id, payload in normal:
                self.assertEqual(db.execute('SELECT payload FROM results WHERE job_id=?', (job_id,)).fetchone()[0], payload)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM model_call_jobs WHERE call_id=4').fetchone()[0], 1)

    def test_legacy_run_resumes_without_protocol_and_rejects_grouped_backend(self):
        self.configure()
        legacy = copy.deepcopy(self.experiment)
        legacy.pop('inference_protocol')
        legacy['batch_size'] = 4
        old = ClefBackend(survey_version=SURVEY_V2_SCENARIO_ID)
        with patch('urllib.request.urlopen', side_effect=self.reply):
            self.assertEqual(run(self.path, self.source, legacy, self.store, old, max_batches=1)['cursor'], 4)
            with self.assertRaisesRegex(ContractError, 'inference protocol'):
                run(self.path, self.source, legacy, self.store, self.grouped)
            self.assertEqual(run(self.path, self.source, legacy, self.store, old)['cursor'], 10)
        self.assertEqual(len(self.bodies), 10)
        self.assertTrue(all(len(body['questions']) == 1 for body in self.bodies))

    def test_group_transport_failure_is_retryable_and_keeps_price_and_purchase(self):
        self.configure()
        def fail_group(request, **kwargs):
            if len(json.loads(request.data).get('questions', {})) == 8:
                raise HTTPException('incomplete grouped HTTP response')
            return self.reply(request, **kwargs)
        with patch('urllib.request.urlopen', side_effect=fail_group):
            failed = run(self.path, self.source, self.experiment, self.store, self.grouped)
        self.assertEqual((failed['cursor'], failed['backend_errors']), (10, 8))
        with patch('urllib.request.urlopen', side_effect=self.reply):
            self.assertEqual(run(self.path, self.source, self.experiment, self.store, self.grouped,
                                 retry_errors=True)['backend_errors'], 0)

    def test_protocol_validation_and_cancelled_preflight(self):
        self.configure(2)
        invalid = {**self.experiment, 'inference_protocol': 'future-version'}
        with self.assertRaisesRegex(ContractError, 'inference protocol'):
            validate_experiment(invalid)
        event = threading.Event()
        with patch.object(self.grouped, 'preflight_batch', side_effect=lambda batch: event.set()) as check:
            self.assertFalse(preflight_jobs(self.grouped, jobs(self.path, self.source, self.experiment), event.is_set))
        self.assertEqual(len(check.call_args.args[0]), 10)


if __name__ == '__main__':
    unittest.main()
