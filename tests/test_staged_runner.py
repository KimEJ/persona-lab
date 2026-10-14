"""Three durable stages keep exact predecessor inputs across pause and repair."""
import copy
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from persona_lab.contracts import canonical, digest
from persona_lab.finite_decision import ClefBackend
from persona_lab.responses import SURVEY_V4_SCENARIO_ID
from persona_lab.runner import jobs, preflight_jobs, run
from persona_lab.survey import STAGED_BASE_DOMAINS, STAGED_PROTOCOL, SURVEY_V4_QUESTIONS
import test_survey_v3 as fixtures


class StagedRunnerTests(unittest.TestCase):
    def setUp(self):
        fixtures.SurveyV3Tests.setUp(self)
        self.scenario['id'] = SURVEY_V4_SCENARIO_ID
        self.backend = ClefBackend(survey_version=SURVEY_V4_SCENARIO_ID,
            inference_protocol=STAGED_PROTOCOL, survey_questions=copy.deepcopy(SURVEY_V4_QUESTIONS))
        self.spec = {'schema_version': '0.1', 'experiment_id': 'staged-runner-test',
            'mode': 'independent_comparison', 'panel': {'selection': 'all'}, 'seed': 17,
            'repeats': 1, 'batch_size': 9, 'assumptions': {}, 'scenario': copy.deepcopy(self.scenario),
            'products': [copy.deepcopy(self.product)], 'questions': copy.deepcopy(SURVEY_V4_QUESTIONS),
            'inference_protocol': STAGED_PROTOCOL}
        self.source = {'schema_version': '0.1', 'source_id': 'survey-test', 'version': 'authored-v1',
            'url': 'local:test', 'license_id': 'LicenseRef-Test', 'license_url': 'local:test',
            'origin': 'project_synthetic_fixture'}
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path, self.store = Path(temporary.name) / 'people.jsonl', Path(temporary.name) / 'run.sqlite'
        self.path.write_text(json.dumps(self.persona.raw, ensure_ascii=False) + '\n')
        self.calls = []

    reply = fixtures.SurveyV3Tests.reply

    def execute(self, **options):
        with patch('urllib.request.urlopen', side_effect=self.reply):
            return run(self.path, self.source, self.spec, self.store, self.backend, **options)

    def records(self):
        with sqlite3.connect(self.store) as db:
            return [json.loads(row[0]) for row in db.execute('SELECT payload FROM results ORDER BY ordinal')]

    def test_pause_each_stage_resumes_exact_history_without_repeating_success(self):
        with patch.object(self.backend, 'preflight_planned_stage') as planned:
            self.assertTrue(preflight_jobs(self.backend, jobs(self.path, self.source, self.spec)))
        self.assertEqual([len(call.args[0]) for call in planned.call_args_list], [7, 1, 1])
        base = self.execute(max_batches=1)
        self.assertEqual((base['cursor'], base['total'], base['status']), (7, 9, 'paused'))
        frozen_base = self.records()
        usage = self.execute(max_batches=1)
        self.assertEqual((usage['cursor'], usage['status']), (8, 'paused'))
        self.assertEqual(self.records()[:7], frozen_base)
        complete = self.execute()
        self.assertEqual((complete['cursor'], complete['backend_errors'], complete['status']), (9, 0, 'completed'))
        self.assertEqual([len(body['questions']) for body in self.calls], [7, 1, 1])
        states = [json.loads(body['state']) for body in self.calls]
        self.assertNotIn('survey_decision_history', states[0])
        self.assertEqual([len(state['survey_decision_history']['records']) for state in states[1:]], [7, 8])
        records = self.records()
        for record, count in ((records[7], 7), (records[8], 8)):
            history = record['survey_history']
            self.assertEqual(record['survey_history_hash'], digest(history))
            self.assertEqual(record['job_id'], digest({'protocol': STAGED_PROTOCOL,
                'logical_job_id': record['logical_job_id'], 'survey_history_hash': digest(history)}))
            self.assertEqual([item['job_id'] for item in history['records']],
                             [item['job_id'] for item in records[:count]])
        with sqlite3.connect(self.store) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM model_calls').fetchone()[0], 3)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM model_call_jobs').fetchone()[0], 9)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM result_revisions').fetchone()[0], 0)

    def test_failed_base_blocks_dependents_and_retry_preserves_healthy_cells(self):
        good_reply = self.reply
        failed_id = SURVEY_V4_QUESTIONS[1]['id']
        def invalid(request, **kwargs):
            response = good_reply(request, **kwargs)
            envelope = json.loads(response.getvalue())
            if failed_id in envelope.get('answers', {}):
                envelope['answers'][failed_id]['probabilities'] = {}
            return io.BytesIO(json.dumps(envelope).encode())
        with patch('urllib.request.urlopen', side_effect=invalid):
            failed = run(self.path, self.source, self.spec, self.store, self.backend)
        self.assertEqual((failed['cursor'], failed['backend_errors']), (9, 3))
        self.assertEqual(len(self.calls), 1)
        before = self.records()
        self.assertEqual([record['backend_error']['type'] for record in before[7:]],
                         ['DependencyError', 'DependencyError'])
        self.assertEqual(self.execute(retry_errors=True)['backend_errors'], 0)
        self.assertEqual([len(body['questions']) for body in self.calls], [7, 7, 1, 1])
        after = self.records()
        for index in (0, 2, 3, 4, 5, 6):
            self.assertEqual(after[index], before[index])
        self.assertNotEqual(after[7]['job_id'], before[7]['job_id'])
        self.assertNotEqual(after[8]['job_id'], before[8]['job_id'])
        with sqlite3.connect(self.store) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM model_call_jobs WHERE call_id=2').fetchone()[0], 1)
            archived = [json.loads(row[0]) for row in db.execute('SELECT payload FROM result_revisions')]
        self.assertIn(before[1], archived)
        self.assertIn(before[7], archived)
        self.assertIn(before[8], archived)

    def test_interrupted_repair_invalidates_successful_followers_and_resume_picks_them(self):
        self.execute()
        before = self.records()
        # A saved repair target with older successful dependents exercises dependency
        # invalidation independently of the initial-pass execution-error gate.
        broken = copy.deepcopy(before[1])
        broken['decision'] = None
        broken['backend_error'] = {'type': 'ContractError', 'message': 'repair target', 'retryable': True}
        with sqlite3.connect(self.store) as db:
            db.execute("UPDATE results SET choice='__backend_error__',status='backend_error',payload=? WHERE ordinal=1",
                       (canonical(broken),))
        original_reply = self.reply
        def changed(request, **kwargs):
            response = original_reply(request, **kwargs)
            envelope = json.loads(response.getvalue())
            key = SURVEY_V4_QUESTIONS[1]['id']
            if key in envelope.get('answers', {}):
                answer = envelope['answers'][key]
                choice = next(option for option in answer['probabilities']
                              if option not in {answer['choice'], 'unknown'})
                answer['choice'] = choice
                answer['probabilities'] = {option: int(option == choice) for option in answer['probabilities']}
            return io.BytesIO(json.dumps(envelope).encode())
        with patch('urllib.request.urlopen', side_effect=changed):
            interrupted = run(self.path, self.source, self.spec, self.store, self.backend,
                              retry_errors=True, max_batches=1)
        self.assertEqual((interrupted['cursor'], interrupted['status']), (9, 'paused'))
        pending = self.records()
        self.assertTrue(all(record['invalidated'] for record in pending[7:]))
        self.assertTrue(all(record['decision'] is None for record in pending[7:]))
        self.assertEqual(self.execute()['status'], 'completed')
        self.assertEqual([len(body['questions']) for body in self.calls], [7, 1, 1, 7, 1, 1])
        after = self.records()
        self.assertNotEqual(after[7]['job_id'], before[7]['job_id'])
        self.assertNotEqual(after[8]['job_id'], before[8]['job_id'])
        with sqlite3.connect(self.store) as db:
            archived = [json.loads(row[0]) for row in db.execute('SELECT payload FROM result_revisions')]
            self.assertEqual(db.execute('SELECT COUNT(*) FROM model_calls').fetchone()[0], 6)
        self.assertIn(before[7], archived)
        self.assertIn(before[8], archived)


if __name__ == '__main__':
    unittest.main()
