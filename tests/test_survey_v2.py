"""Bounded checks for independent measurements and frozen older requests."""
import copy
import hashlib
import io
import json
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from persona_lab.backends import FixtureBackend
from persona_lab.contracts import ContractError, Job, Persona, canonical, validate_decision, validate_experiment
from persona_lab.finite_decision import ClefBackend
from persona_lab.responses import QUESTIONS, DECISION_SCENARIO_ID, SURVEY_SCENARIO_ID, SURVEY_V2_SCENARIO_ID, price_bands
from persona_lab.runner import run
from persona_lab.survey import SURVEY_QUESTIONS, SURVEY_V2_DOMAINS, SURVEY_V2_QUESTIONS, question_info


class SurveyV2Tests(unittest.TestCase):
    def setUp(self):
        persona = Persona('person-id', 'uuid-secret', {}, {'uuid': 'uuid-secret', 'age': 32,
                          'persona': 'macOS에서 매일 메모를 검색한다.', 'professional_persona': '별도 미사용 서술'}, 'hash-secret', {}, {}, {})
        product = {'id': 'item-secret', 'name': '메모 도구', 'features': [],
                   'intro': '검색과 태그로 메모를 정리합니다.',
                   'document': '## 주요 기능\n검색과 태그로 메모를 정리합니다.\n가격: 900 JPY 일시불',
                   'price': {'amount_minor': 2000, 'currency': 'JPY', 'billing': 'one_time'},
                   'price_state': 'paid', 'price_origin': 'explicit',
                   'valuation_unit': {'currency': 'JPY', 'billing': 'one_time'}, 'valuation_bands': price_bands('JPY')}
        self.job = Job(0, 'job-secret', persona, product, copy.deepcopy(SURVEY_V2_QUESTIONS[0]), 0, 123,
                       {'id': SURVEY_V2_SCENARIO_ID, 'initial_state_id': 'initial-v1', 'events': []}, {})
        self.backend = ClefBackend(revision='model-sha', runtime_revision='runtime-sha', survey_version=SURVEY_V2_SCENARIO_ID)

    def stage(self, domain, **kwargs):
        question = copy.deepcopy(next(question for question in SURVEY_V2_QUESTIONS if question['domain'] == domain))
        return replace(self.job, question=question, **kwargs)

    def spec(self):
        return {'schema_version': '0.1', 'experiment_id': 'survey-test', 'mode': 'independent_comparison',
                'panel': {'selection': 'random', 'sample_size': 1, 'sample_seed': 17,
                          'sampling_version': 'hash-rank-v1', 'selected_uuids': ['uuid-secret']},
                'seed': 7, 'repeats': 1, 'batch_size': 4, 'assumptions': {},
                'scenario': copy.deepcopy(self.job.scenario), 'products': [copy.deepcopy(self.job.product)],
                'questions': copy.deepcopy(SURVEY_V2_QUESTIONS)}

    @staticmethod
    def envelope(body, choice):
        key, question = next(iter(body['questions'].items()))
        return {'answers': {key: {'type': 'choice', 'choice': choice,
                'probabilities': {option: int(option == choice) for option in question['criteria']}}},
                'usage': {'input_tokens': 100, 'output_tokens': 0}}

    def test_ten_independent_requests_never_consume_prior_choices(self):
        self.assertEqual(SURVEY_V2_DOMAINS, ('relevance', 'current_solution', 'clarity', 'benefit', 'differentiation',
                                          'credibility', 'switching', 'usage', 'fair_price', 'purchase'))
        self.assertTrue(self.backend.backend_id.endswith(':survey-choice-v2'))
        for question in SURVEY_V2_QUESTIONS:
            job = replace(self.job, question=question)
            body = self.backend.request_body(job)
            state = json.loads(body['state'])
            self.assertNotIn('prior_assessments', state)
            self.assertEqual(body, self.backend.request_body(replace(job, assessments={'usage': {'choice': 'error'},
                              'fair_price': {'choice': 'price_3'}, 'other': {'reason': 'generated rationale'}})))
            self.assertEqual(body, self.backend.request_body(replace(job, job_id='changed', seed=99, repeat=4)))
            self.assertEqual(set(body['questions']['decision']['criteria']), set(question['choices']) - {'not_run'})
            self.assertNotIn('secret', body['state'])
            if question['domain'] != 'purchase':
                self.assertNotIn('offer', state)
                self.assertNotIn('900', state['product']['document'])
                changed = replace(job, product={**job.product, 'price': {**job.product['price'], 'amount_minor': 990000},
                                               'document': job.product['document'].replace('900', '990000')})
                self.assertEqual(body, self.backend.request_body(changed))
            else:
                self.assertEqual(state['offer']['amount_minor'], 2000)
                self.assertNotIn('valuation_bands', state)
            self.assertEqual('not_applicable' in question['choices'], question['domain'] in {'benefit', 'differentiation', 'switching'})
        self.assertEqual(question_info('usage', SURVEY_V2_SCENARIO_ID)['choices']['consider'], '사용을 고려함')
        self.assertNotIn('consider', question_info('usage')['choices'])

    def test_explicit_price_grid_validation_keeps_old_grid_contract(self):
        spec = self.spec()
        explicit = [{'id': 'price_0', 'low_minor': 0, 'high_minor': 498},
                    {'id': 'price_1', 'low_minor': 499, 'high_minor': 1298},
                    {'id': 'price_2', 'low_minor': 1299, 'high_minor': 9998},
                    {'id': 'price_3', 'low_minor': 9999, 'high_minor': None}]
        for bands in (explicit, []):
            spec['products'][0]['valuation_bands'] = bands
            validate_experiment(spec)
        spec['products'][0]['valuation_bands'] = explicit
        body = self.backend.request_body(self.stage('fair_price', product=spec['products'][0]))
        self.assertEqual(body['questions']['decision']['criteria']['price_0'], '499 JPY 미만 · 일시불')
        for change in ('gap', 'overlap', 'nonzero_start', 'reversed', 'last_finite', 'wrong_id', 'fraction', 'boolean', 'missing_band'):
            candidate = copy.deepcopy(spec)
            bands = candidate['products'][0]['valuation_bands']
            if change == 'gap': bands[1]['low_minor'] += 1
            if change == 'overlap': bands[1]['low_minor'] -= 1
            if change == 'nonzero_start': bands[0]['low_minor'] = 1
            if change == 'reversed': bands[1]['high_minor'] = 498
            if change == 'last_finite': bands[3]['high_minor'] = 10000
            if change == 'wrong_id': bands[1]['id'] = 'price_9'
            if change == 'fraction': bands[0]['high_minor'] = 498.5
            if change == 'boolean': bands[0]['low_minor'] = False
            if change == 'missing_band': bands.pop()
            with self.subTest(change=change), self.assertRaises(ContractError):
                validate_experiment(candidate)
        legacy = copy.deepcopy(spec)
        legacy['scenario']['id'] = SURVEY_SCENARIO_ID
        legacy['questions'] = copy.deepcopy(SURVEY_QUESTIONS)
        with self.assertRaises(ContractError): validate_experiment(legacy)
        legacy['products'][0]['valuation_bands'] = price_bands('JPY')
        validate_experiment(legacy)
        for price in ({'amount_minor': True, 'currency': 'JPY', 'billing': 'one_time'},
                      {'amount_minor': 10, 'currency': 'XYZ', 'billing': 'one_time'}):
            candidate = copy.deepcopy(spec)
            candidate['products'][0]['price'] = price
            with self.assertRaises(ContractError): validate_experiment(candidate)
        spec['questions'][7]['choices'].append('not_applicable')
        with self.assertRaises(ContractError): validate_experiment(spec)

    def test_unset_measurements_skip_model_without_blocking_other_questions(self):
        product = {**self.job.product, 'price': None, 'valuation_bands': []}
        with patch('urllib.request.urlopen') as request, patch('persona_lab.backends.check_dependencies') as dependency:
            for domain in ('fair_price', 'purchase'):
                job = self.stage(domain, product=product)
                result = self.backend.decide(job)
                self.backend.preflight(job)
                self.assertEqual((result.choice, result.status), ('not_run', 'not_run'))
                self.assertIsNone(result.option_probabilities)
                validate_decision(result, job)
            request.assert_not_called()
            dependency.assert_not_called()
        job = self.stage('usage', product=product)
        def reply(request, **kwargs):
            body = json.loads(request.data)
            return io.BytesIO(json.dumps(self.envelope(body, 'consider')).encode())
        with patch('urllib.request.urlopen', side_effect=reply), patch('persona_lab.backends.check_dependencies') as dependency:
            result = self.backend.decide(job)
        self.assertEqual((result.choice, result.status), ('consider', 'ok'))
        dependency.assert_not_called()
        validate_decision(result, job)

    def test_unknown_classification_na_and_free_refusal_remain_distinct(self):
        for domain, choice in (('differentiation', 'unknown'), ('benefit', 'not_applicable'), ('purchase', 'decline')):
            product = {**self.job.product, 'price': {**self.job.product['price'], 'amount_minor': 0}}
            job = self.stage(domain, product=product)
            for auxiliary_failure in (False, True) if choice == 'unknown' else (False,):
                bodies = []
                def reply(request, **kwargs):
                    body = json.loads(request.data); bodies.append(body)
                    if 'missing_information' in body['questions']:
                        self.assertIn('alternatives_info', body['questions']['missing_information']['criteria'])
                        if auxiliary_failure: raise OSError('classifier unavailable')
                        answer = self.envelope(body, 'alternatives_info')
                    else:
                        answer = self.envelope(body, choice)
                    return io.BytesIO(json.dumps(answer).encode())
                with patch('urllib.request.urlopen', side_effect=reply), patch('persona_lab.backends.check_dependencies') as dependency:
                    result = self.backend.decide(job)
                dependency.assert_not_called()
                validate_decision(result, job)
                self.assertEqual(result.choice, choice)
                self.assertIsNone(result.valuation)
                self.assertFalse(any(ref.startswith('assessments.') for ref in result.evidence_refs))
                if choice == 'unknown':
                    self.assertEqual(result.status, 'insufficient_information')
                    self.assertEqual(result.option_probabilities['unknown'], 1)
                    self.assertEqual(bodies[0]['state'], bodies[1]['state'])
                    self.assertEqual(result.missing_information, () if auxiliary_failure else ('비교할 대안의 기능과 조건',))
                    self.assertEqual(result.diagnostic_error is not None, auxiliary_failure)
                else:
                    self.assertEqual((result.status, result.missing_information, result.diagnostic_error), ('ok', (), None))
                    if domain == 'purchase':
                        self.assertEqual(bodies[0]['questions']['decision']['criteria']['decline'], '무료여도 사용하지 않겠음')

    def test_runner_resume_and_retry_keep_final_choice_independent_of_failures(self):
        spec = self.spec()
        source = {'schema_version': '0.1', 'source_id': 'survey-test', 'version': 'authored-v1',
                  'url': 'local:test', 'license_id': 'LicenseRef-Test', 'license_url': 'local:test', 'origin': 'project_synthetic_fixture'}
        observed = []
        class Fault(FixtureBackend):
            failed = True
            def decide(inner, job):
                observed.append(job)
                self.assertIsNone(job.assessments)
                if job.question['domain'] == 'fair_price' and inner.failed:
                    raise ContractError('intentional fair-price failure')
                return super().decide(job)
        backend = Fault()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'people.jsonl'; store = Path(temporary) / 'run.sqlite'
            path.write_text(json.dumps(self.job.persona.raw, ensure_ascii=False) + '\n')
            partial = run(path, source, spec, store, backend, max_batches=1)
            self.assertEqual((partial['cursor'], partial['total']), (4, 10))
            with sqlite3.connect(store) as db:
                preserved = db.execute('SELECT payload FROM results ORDER BY ordinal').fetchall()
            completed = run(path, source, spec, store, backend)
            self.assertEqual((completed['cursor'], completed['backend_errors']), (10, 1))
            with sqlite3.connect(store) as db:
                payloads = db.execute('SELECT payload FROM results ORDER BY ordinal').fetchall()
            self.assertEqual(payloads[:4], preserved)
            records = [json.loads(payload) for (payload,) in payloads]
            self.assertFalse(any('assessments' in record for record in records))
            self.assertIsNotNone(records[-1]['decision'])
            self.assertEqual(records[-2]['backend_error']['type'], 'ContractError')
            self.assertTrue(all(job.product['price'] is None for job in observed if job.question['domain'] != 'purchase'))
            backend.failed = False
            retried = run(path, source, spec, store, backend, retry_errors=True)
            self.assertEqual(retried['backend_errors'], 0)
            self.assertEqual([job.question['domain'] for job in observed], [*SURVEY_V2_DOMAINS, 'fair_price'])

    def test_legacy_finite_and_eight_stage_request_fingerprints_are_preserved(self):
        legacy = ClefBackend(revision='model-sha', runtime_revision='runtime-sha', survey=True)
        self.assertTrue(legacy.backend_id.endswith(':survey-choice-v1'))
        prior = {'usage': {'job_id': 'usage-secret', 'choice': 'use', 'reason': 'free prose'},
                 'fair_price': {'job_id': 'fair-secret', 'choice': 'price_1'}}
        expected = ('42842db3a41774700f72a6bd77783011da2b7fd2a87a5a7bfb8975a165a484a5',
                    'aae6c869220e7c6e8315b2657335de1bbe7d41b4472c05cc4f29ea10efe4a64b',
                    '6b74c23429751c7b63c2bff0849cc2d9b83e08a46e7856481bd0e65c06281842',
                    '2d588c5b684b5c26b583ca3e6dbeb23fe53af866f99bf7fa0c25211838c8e47e',
                    '05aad254735322536a74f082a391b631b38b2d1623d96afe5a8e7d72aa131a34',
                    'e60e55efaebffba26f95bc483eda760aeaa9df46e589a641e08a7bef155fcbf7',
                    '230c6b3ed9b871a23d4647535019e8535d5fbccc1088205ce309c7a24dcc3a68',
                    '588cb803a575ab80f75e64e44c9ee7677cdcc4eafde40a7810885b431e6f5603')
        for question, fingerprint in zip(SURVEY_QUESTIONS, expected):
            job = replace(self.job, question=question, scenario={**self.job.scenario, 'id': SURVEY_SCENARIO_ID}, assessments=prior)
            self.assertEqual(hashlib.sha256(canonical(legacy.request_body(job)).encode()).hexdigest(), fingerprint)
        finite = ClefBackend(revision='model-sha', runtime_revision='runtime-sha')
        self.assertTrue(finite.backend_id.endswith(':finite-choice-v1'))
        expected = ('34696da166f9ff1514b483db965f7dcbac3a2c3d956af186c2b6c8256544437a',
                    '202bc5e203e08eb1152a0d0a2f65e3189fc9a5db50c3cab0b19fce63322c31b8',
                    '5876dbb9ba23e0aa8baaa77ab3e819eeaf08b8534cb9c29bdcd7ea09281337b7')
        for question, fingerprint in zip(QUESTIONS, expected):
            job = replace(self.job, question=question, scenario={**self.job.scenario, 'id': DECISION_SCENARIO_ID}, assessments=prior)
            self.assertEqual(hashlib.sha256(canonical(finite.request_body(job)).encode()).hexdigest(), fingerprint)


if __name__ == '__main__':
    unittest.main()
