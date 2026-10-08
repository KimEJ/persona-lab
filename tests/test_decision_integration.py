import copy
import io
import json
import sqlite3
import unittest
from unittest.mock import patch

import test_product as fixtures
import test_responses as responses
from persona_lab.backends import FixtureBackend
from persona_lab.finite_decision import ClefBackend
from persona_lab.responses import DECISION_QUESTIONS, DECISION_SCENARIO_ID, LINKED_QUESTIONS, LINKED_SCENARIO_ID, QUESTIONS
from persona_lab.runner import run


class DecisionIntegrationTests(unittest.TestCase):
    setUp = fixtures.ProductTests.setUp
    finish = fixtures.ProductTests.finish
    configure = responses.ResponseTests.configure

    def test_pause_retry_preserves_lineage_distributions_and_unknown_audit(self):
        spec = self.configure('paid', items=2, repeats=2)
        # Preserve the shipped three-stage finite contract and its raw audit.
        spec['scenario']['id'] = DECISION_SCENARIO_ID
        spec['questions'] = copy.deepcopy(DECISION_QUESTIONS)
        directory = self.app.directory(self.draft['id'])
        frozen = dict(self.draft)
        frozen['workflow'] = DECISION_SCENARIO_ID
        frozen.pop('run', None)
        frozen.pop('legacy_items', None)
        (directory / 'run.json').write_text(json.dumps({'draft': frozen, 'source': self.source, 'spec': spec}))
        store = directory / 'run.sqlite'
        observed = []
        wire_requests = []
        fail_price = True

        class Observe(ClefBackend):
            def decide(inner, job):
                observed.append(job)
                return super().decide(job)

        backend = Observe()

        def reply(request, **kwargs):
            nonlocal fail_price
            self.assertTrue(request.full_url.endswith('/v1/systemone'))
            wire_requests.append(request.data.decode('utf-8'))
            body = json.loads(request.data)
            question_id, question = next(iter(body['questions'].items()))
            options = question['criteria']
            if question_id == 'missing_information':
                choice = 'usage_environment'
            elif 'use' in options:
                choice = 'unknown'
            elif 'price_0' in options:
                choice = 'price_1'
            else:
                choice = 'decline'
                priors = json.loads(body['state'])['prior_assessments']
                self.assertEqual(priors['usage']['choice'], 'unknown')
                self.assertEqual(priors['fair_price']['choice'], 'price_1')
            probabilities = {key: float(key == choice) for key in options}
            if choice == 'price_1' and fail_price:
                fail_price = False
                probabilities[choice] = 0
            answer = {'answers': {question_id: {'type': 'choice', 'choice': choice, 'probabilities': probabilities}},
                      'usage': {'input_tokens': 100, 'output_tokens': 0}}
            return io.BytesIO(json.dumps(answer).encode())

        with patch('urllib.request.urlopen', side_effect=reply):
            paused = run(self.app.data_path, self.source, spec, store, backend, max_batches=2)
            self.assertEqual((paused['status'], paused['cursor']), ('paused', 2))
            completed = run(self.app.data_path, self.source, spec, store, backend)
            self.assertEqual((completed['cursor'], completed['backend_errors']), (48, 2))
            with sqlite3.connect(store) as db:
                preserved = db.execute("SELECT job_id,payload FROM results WHERE status!='backend_error'").fetchall()
                failures = [json.loads(row[0]) for row in db.execute("SELECT payload FROM results WHERE status='backend_error'")]
            self.assertEqual({record['backend_error']['type'] for record in failures}, {'ContractError', 'DependencyError'})
            retried = run(self.app.data_path, self.source, spec, store, backend, retry_errors=True)
            self.assertEqual((retried['status'], retried['backend_errors']), ('completed', 0))

        with sqlite3.connect(store) as db:
            for job_id, payload in preserved:
                self.assertEqual(db.execute('SELECT payload FROM results WHERE job_id=?', (job_id,)).fetchone()[0], payload)
            records = [json.loads(row[0]) for row in db.execute('SELECT payload FROM results ORDER BY ordinal')]
            calls = db.execute('SELECT job_id,request,response,error FROM model_calls ORDER BY id').fetchall()
        self.assertIsNone(backend.audit)
        self.assertEqual(len(calls), 65)
        self.assertEqual([request for _, request, _, _ in calls], wire_requests)
        by_id = {record['job_id']: record for record in records}
        for record in records:
            decision = record['decision']
            self.assertEqual(decision['evidence_semantics'], 'supplied_input_only')
            self.assertEqual(decision['probability_semantics'], 'model_option_distribution')
            self.assertEqual(sum(decision['option_probabilities'].values()), 1)
            self.assertEqual(decision['option_probabilities'][decision['choice']], 1)
            self.assertIsNone(decision['valuation'])
            self.assertEqual(decision['evidence'], [])
            if decision['choice'] != 'unknown':
                self.assertEqual(decision['reason'], '')
            if record['domain'] != 'purchase':
                self.assertIsNone(record['assessments'])
                continue
            self.assertEqual(set(record['assessments']), {'usage', 'fair_price'})
            for prior in record['assessments'].values():
                earlier = by_id[prior['job_id']]
                for key in ('persona_id', 'product_id', 'repeat'):
                    self.assertEqual(earlier[key], record[key])
        for record in records:
            if record['domain'] == 'usage':
                self.assertEqual(record['decision']['missing_information'], ['사용 환경과 도입 가능 조건'])
                attempts = [json.loads(request) for job_id, request, _, _ in calls if job_id == record['job_id']]
                self.assertEqual([list(body['questions']) for body in attempts], [['decision'], ['missing_information']])
        self.assertTrue(all(response is not None and error is None for _, _, response, error in calls))
        self.assertTrue(all(json.loads(response)['usage']['output_tokens'] == 0 for _, _, response, _ in calls))
        self.assertEqual(len([job for job in observed if job.question['domain'] == 'purchase']), 17)
        exported = json.loads(self.app.export(self.draft['id'], 'json')[0])
        self.assertEqual(len(exported['model_calls']), 65)
        self.assertTrue(all(person['items'][0]['fair_price']['valuation'] is None for person in self.app.responses(self.draft['id'])['people']))

    def test_frozen_response_contracts_resume_without_new_probability_fields(self):
        for scenario, questions in [('product-response-v1', QUESTIONS), (LINKED_SCENARIO_ID, LINKED_QUESTIONS)]:
            with self.subTest(scenario=scenario):
                spec = self.configure('paid')
                spec['scenario']['id'] = scenario
                spec['questions'] = copy.deepcopy(questions)
                frozen = {**self.draft, 'workflow': scenario}
                frozen.pop('run', None)
                frozen.pop('legacy_items', None)
                directory = self.app.directory(self.draft['id'])
                manifest = directory / 'run.json'
                manifest.write_text(json.dumps({'draft': frozen, 'source': self.source, 'spec': spec}))
                original_manifest = manifest.read_bytes()
                store = directory / 'run.sqlite'
                run(self.app.data_path, self.source, spec, store, FixtureBackend(), max_batches=1)
                with sqlite3.connect(store) as db:
                    before = db.execute('SELECT job_id,payload FROM results').fetchall()
                self.app.start(self.draft['id'])
                self.assertEqual(self.finish(self.draft['id'])['backend_errors'], 0)
                self.assertEqual(manifest.read_bytes(), original_manifest)
                self.assertEqual(self.app.get(self.draft['id'])['workflow'], scenario)
                self.assertEqual(self.app.responses(self.draft['id'])['workflow'], scenario)
                with sqlite3.connect(store) as db:
                    for job_id, payload in before:
                        self.assertEqual(db.execute('SELECT payload FROM results WHERE job_id=?', (job_id,)).fetchone()[0], payload)
                    for payload, in db.execute('SELECT payload FROM results'):
                        decision = json.loads(payload)['decision']
                        self.assertNotIn('option_probabilities', decision)
                        self.assertNotIn('probability_semantics', decision)


if __name__ == '__main__':
    unittest.main()
