import copy
import io
import json
import unittest
from dataclasses import replace
from unittest.mock import patch

from persona_lab.contracts import ContractError, DependencyError, Job, Persona, validate_decision
from persona_lab.finite_decision import ClefBackend, SCENARIO_ID
from persona_lab.responses import QUESTIONS, price_bands


class FiniteDecisionTests(unittest.TestCase):
    def setUp(self):
        persona = Persona('person-id', 'uuid-secret', {}, {'uuid': 'uuid-secret', 'age': 32,
                          'persona': 'macOS에서 매일 메모를 검색한다.', 'professional_persona': '별도 미사용 서술'}, 'hash-secret', {}, {}, {})
        product = {'id': 'item-secret', 'name': '메모 도구',
                   'intro': '검색과 태그로 메모를 정리합니다.',
                   'document': '## 주요 기능\n검색과 태그로 메모를 정리합니다.\n가격: 900 JPY 일시불',
                   'price': {'amount_minor': 2000, 'currency': 'JPY', 'billing': 'one_time'},
                   'price_state': 'paid', 'price_origin': 'explicit',
                   'valuation_unit': {'currency': 'JPY', 'billing': 'one_time'}, 'valuation_bands': price_bands('JPY')}
        self.job = Job(0, 'job-secret', persona, product, copy.deepcopy(QUESTIONS[0]), 0, 123,
                       {'id': SCENARIO_ID, 'initial_state_id': 'initial-v1', 'events': []}, {})
        self.backend = ClefBackend(revision='model-sha', runtime_revision='runtime-sha')
        self.requests, self.audit = [], []
        def audit(action, identifier, payload):
            self.audit.append((action, identifier, payload))
            return len(self.audit)
        self.backend.audit = audit

    def stage(self, domain, **kwargs):
        question = copy.deepcopy(next(question for question in QUESTIONS if question['domain'] == domain))
        return replace(self.job, question=question, **kwargs)

    def envelope(self, body, choice=None, probabilities=None):
        key, question = next(iter(body['questions'].items()))
        options = list(question['criteria'])
        choice = choice or options[0]
        probabilities = probabilities or {option: int(option == choice) for option in options}
        return {'model': 'clef-flash', 'answers': {key: {'type': 'choice', 'choice': choice, 'confidence': 1,
                'probabilities': probabilities}}, 'usage': {'input_tokens': 100, 'output_tokens': 0}}

    def reply(self, request, **kwargs):
        self.assertTrue(request.full_url.endswith('/v1/systemone'))
        body = json.loads(request.data)
        self.requests.append(body)
        return io.BytesIO(json.dumps(self.envelope(body)).encode())

    def test_price_blind_authoritative_fields_and_supplied_persona_only(self):
        for domain in ('usage', 'fair_price'):
            job = self.stage(domain)
            body = self.backend.request_body(job)
            state = json.loads(body['state'])
            self.assertNotIn('900', body['state'])
            self.assertNotIn('2000', json.dumps(state['product']))
            self.assertNotIn('price', state['product'])
            self.assertNotIn('price_state', state['product'])
            self.assertEqual(state['product']['name'], '메모 도구')
            self.assertEqual(state['persona']['persona'], self.job.persona.raw['persona'])
            self.assertNotIn('professional_persona', state['persona'])
            self.assertIn('상품의 대상 고객', body['questions']['decision']['instructions'])
            self.assertEqual(set(body), {'model', 'state', 'questions'})
        state = json.loads(self.backend.request_body(self.job)['state'])
        self.assertNotIn('valuation_bands', state)

    def test_semantic_repeat_inputs_are_identical_without_execution_ids(self):
        repeated = replace(self.job, ordinal=999, job_id='another-job', repeat=5, seed=999,
                           persona=replace(self.job.persona, persona_id='another-person', uuid='another-uuid',
                                           content_hash='another-hash', raw={**self.job.persona.raw, 'uuid': 'changed'}),
                           product={**self.job.product, 'id': 'another-item'})
        self.assertEqual(self.backend.request_body(self.job), self.backend.request_body(repeated))
        self.assertNotIn('secret', self.backend.request_body(self.job)['state'])
        self.assertIn('model-sha:runtime-sha:finite-choice-v1', self.backend.backend_id)

    def test_band_choices_use_major_units_without_generating_a_point_price(self):
        product = {**self.job.product, 'valuation_unit': {'currency': 'USD', 'billing': 'monthly'},
                   'valuation_bands': price_bands('USD')}
        job = self.stage('fair_price', product=product)
        body = self.backend.request_body(job)
        self.assertEqual(body['questions']['decision']['criteria']['price_0'], '10 USD 미만 · 월간')
        self.assertEqual(json.loads(body['state'])['valuation_bands'][0]['high_minor'], 999)
        with patch('urllib.request.urlopen', side_effect=self.reply):
            decision = self.backend.decide(job)
        self.assertEqual(decision.choice, 'price_0')
        self.assertIsNone(decision.valuation)
        self.assertEqual(decision.reason, '')
        self.assertEqual(decision.evidence_semantics, 'supplied_input_only')
        validate_decision(decision, job)

    def test_purchase_has_actual_offer_and_thin_predecessors_without_identity(self):
        assessments = {'usage': {'job_id': 'usage-secret', 'choice': 'use', 'reason': 'free prose'},
                       'fair_price': {'job_id': 'fair-secret', 'choice': 'price_1',
                                      'valuation': {'amount_minor': 1001, 'currency': 'JPY', 'billing': 'one_time'}}}
        job = self.stage('purchase', assessments=assessments)
        body = self.backend.request_body(job)
        state = json.loads(body['state'])
        self.assertEqual(state['offer']['amount_minor'], 2000)
        self.assertEqual(state['prior_assessments']['usage'], {'choice': 'use'})
        self.assertEqual(state['prior_assessments']['fair_price']['band'], price_bands('JPY')[1])
        for forbidden in ('secret', 'free prose', '1001'):
            self.assertNotIn(forbidden, body['state'])
        self.assertNotIn('not_run', body['questions']['decision']['criteria'])
        with patch('urllib.request.urlopen', side_effect=self.reply):
            result = self.backend.decide(job)
        self.assertTrue({'product.price', 'assessments.usage', 'assessments.fair_price'} <= set(result.evidence_refs))
        validate_decision(result, job)

    def test_free_decline_is_an_explicit_choice_and_absent_offer_skips_model(self):
        product = {**self.job.product, 'price': {**self.job.product['price'], 'amount_minor': 0}}
        job = self.stage('purchase', product=product, assessments={'usage': {'choice': 'not_use'}, 'fair_price': {'choice': 'unknown'}})
        body = self.backend.request_body(job)
        self.assertEqual(body['questions']['decision']['criteria']['decline'], '무료여도 사용하지 않겠음')
        job = replace(job, product={**product, 'price': None})
        with patch('urllib.request.urlopen') as request:
            result = self.backend.decide(job)
            self.backend.preflight(job)
        request.assert_not_called()
        self.assertEqual((result.choice, result.status), ('not_run', 'not_run'))
        self.assertIsNone(result.option_probabilities)
        self.assertEqual(self.audit, [])

    def test_dependencies_fail_before_model_call_but_not_initial_preflight(self):
        job = self.stage('purchase')
        with patch('urllib.request.urlopen') as request:
            self.backend.preflight(job)
            with self.assertRaises(DependencyError):
                self.backend.decide(job)
        request.assert_not_called()
        self.assertEqual(self.audit, [])

    def test_unknown_followup_is_separate_and_cannot_replace_primary_distribution(self):
        primary = {'use': .1, 'not_use': .1, 'unknown': .8}
        def reply(request, **kwargs):
            body = json.loads(request.data); self.requests.append(body)
            if 'decision' in body['questions']:
                result = self.envelope(body, 'unknown', primary)
            else:
                self.assertIn('value_basis', body['questions']['missing_information']['criteria'])
                result = self.envelope(body, 'current_method')
            return io.BytesIO(json.dumps(result).encode())
        with patch('urllib.request.urlopen', side_effect=reply):
            decision = self.backend.decide(self.job)
        self.assertEqual(decision.choice, 'unknown')
        self.assertEqual(decision.option_probabilities, primary)
        self.assertEqual(decision.probability_semantics, 'model_option_distribution')
        self.assertEqual(decision.missing_information, ('현재 사용하는 도구와 불편한 점',))
        self.assertIn('missing.current_method', decision.reason_codes)
        self.assertEqual(decision.reason, '사용 의향을 판단하지 못했습니다. 확인이 필요한 정보: 현재 사용하는 도구와 불편한 점.')
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(self.requests[0]['state'], self.requests[1]['state'])
        self.assertEqual([event[0] for event in self.audit], ['start', 'finish', 'start', 'finish'])
        validate_decision(decision, self.job)

    def test_auxiliary_failure_preserves_completed_unknown_and_primary_distribution(self):
        primary = {'use': .1, 'not_use': .1, 'unknown': .8}
        for failure in ('transport', 'invalid_response'):
            with self.subTest(failure=failure):
                self.audit.clear()
                def reply(request, **kwargs):
                    body = json.loads(request.data)
                    if 'decision' in body['questions']:
                        return io.BytesIO(json.dumps(self.envelope(body, 'unknown', primary)).encode())
                    if failure == 'transport':
                        raise OSError('classification unavailable')
                    return io.BytesIO(json.dumps(self.envelope(body, 'current_method', {'current_method': 1})).encode())
                with patch('urllib.request.urlopen', side_effect=reply):
                    decision = self.backend.decide(self.job)
                self.assertEqual((decision.choice, decision.status), ('unknown', 'insufficient_information'))
                self.assertEqual(decision.option_probabilities, primary)
                self.assertEqual(decision.probability_semantics, 'model_option_distribution')
                self.assertEqual(decision.missing_information, ())
                self.assertEqual(decision.reason, '사용 의향을 판단하지 못했습니다.')
                self.assertIn('missing_information_failed', decision.reason_codes)
                self.assertEqual(decision.diagnostic_error['type'], 'OSError' if failure == 'transport' else 'ContractError')
                self.assertTrue(decision.diagnostic_error['message'])
                self.assertEqual([event[0] for event in self.audit], ['start', 'finish', 'start', 'finish'])
                self.assertIn('response', self.audit[1][2])
                self.assertIn('error' if failure == 'transport' else 'response', self.audit[3][2])
                validate_decision(decision, self.job)

    def test_argmax_exact_tie_is_broken_by_canonical_code_not_server_order(self):
        reversed_job = replace(self.job, question={**self.job.question, 'choices': list(reversed(self.job.question['choices']))})
        def reply(request, **kwargs):
            body = json.loads(request.data)
            self.assertEqual(list(body['questions']['decision']['criteria']), ['unknown', 'not_use', 'use'])
            return io.BytesIO(json.dumps(self.envelope(body, 'use', {'use': .5, 'not_use': .5, 'unknown': 0})).encode())
        with patch('urllib.request.urlopen', side_effect=reply):
            decision = self.backend.decide(reversed_job)
        self.assertEqual(decision.choice, 'not_use')

    def test_invalid_distributions_or_server_argmax_fail_after_raw_audit(self):
        invalid = [
            {'use': 1, 'not_use': 0}, {'use': 1, 'not_use': 0, 'unknown': 0, 'extra': 0},
            {'use': 1.1, 'not_use': -.1, 'unknown': 0}, {'use': True, 'not_use': 0, 'unknown': 0},
            {'use': float('nan'), 'not_use': 0, 'unknown': 0}, {'use': float('inf'), 'not_use': 0, 'unknown': 0},
            {'use': .5, 'not_use': .4, 'unknown': 0}, {'use': .1, 'not_use': .9, 'unknown': 0},
        ]
        for probabilities in invalid:
            with self.subTest(probabilities=probabilities):
                def reply(request, **kwargs):
                    body = json.loads(request.data)
                    return io.BytesIO(json.dumps(self.envelope(body, 'use', probabilities)).encode())
                with patch('urllib.request.urlopen', side_effect=reply), self.assertRaises(ContractError):
                    self.backend.decide(self.job)
                self.assertEqual(self.audit[-1][0], 'finish')
                self.assertIn('response', self.audit[-1][2])

    def test_nonzero_generation_wrong_question_or_untyped_answer_is_error(self):
        for mutation in ('tokens', 'wrong_id', 'wrong_type'):
            with self.subTest(mutation=mutation):
                def reply(request, **kwargs):
                    body = json.loads(request.data); result = self.envelope(body)
                    if mutation == 'tokens': result['usage']['output_tokens'] = 1
                    if mutation == 'wrong_id': result['answers']['other'] = result['answers'].pop('decision')
                    if mutation == 'wrong_type': result['answers']['decision']['type'] = 'score'
                    return io.BytesIO(json.dumps(result).encode())
                with patch('urllib.request.urlopen', side_effect=reply), self.assertRaises(ContractError):
                    self.backend.decide(self.job)

    def test_transport_and_parse_errors_preserve_attempts_and_do_not_fallback(self):
        with patch('urllib.request.urlopen', side_effect=OSError('offline')):
            with self.assertRaisesRegex(OSError, 'offline'):
                self.backend.decide(self.job)
        self.assertEqual(self.audit[-1][2]['error'], 'offline')
        with patch('urllib.request.urlopen', return_value=io.BytesIO(b'not json')):
            with self.assertRaises(ContractError):
                self.backend.decide(self.job)
        self.assertEqual(self.audit[-1][2]['response'], 'not json')
        with patch('urllib.request.urlopen', side_effect=self.reply):
            self.assertEqual(self.backend.decide(self.job).choice, 'use')
        self.assertEqual([event[0] for event in self.audit], ['start', 'finish'] * 3)
        self.assertEqual(len({event[1] for event in self.audit if event[0] == 'finish'}), 3)

    def test_long_input_is_not_truncated_and_checked_again_with_priors(self):
        document = '가' * 20000
        job = replace(self.job, product={**self.job.product, 'document': document, 'intro': document})
        self.assertEqual(json.loads(self.backend.request_body(job)['state'])['product']['document'], document)
        def tokenize(request, **kwargs):
            self.assertTrue(request.full_url.endswith('/tokenize'))
            self.assertIn(document, json.loads(request.data)['content'])
            return io.BytesIO(json.dumps({'tokens': [1] * 7169}).encode())
        with patch('urllib.request.urlopen', side_effect=tokenize), self.assertRaisesRegex(ContractError, '입력 한도'):
            self.backend.preflight(job)
        self.assertEqual(self.audit, [])

    def test_endpoint_requires_loopback_and_matching_scenario(self):
        for endpoint in ('https://localhost:8081', 'http://example.com:8081', 'http://localhost:65536', 'http://127.0.0.1:8081/path'):
            with self.assertRaises(ContractError):
                ClefBackend(endpoint)
        with self.assertRaises(ContractError):
            self.backend.request_body(replace(self.job, scenario={**self.job.scenario, 'id': 'product-response-v2'}))


if __name__ == '__main__':
    unittest.main()
