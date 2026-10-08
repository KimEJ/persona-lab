import copy
import hashlib
import io
import json
import unittest
from dataclasses import replace
from unittest.mock import patch

from persona_lab.contracts import DependencyError, Job, Persona, canonical, validate_decision
from persona_lab.finite_decision import ClefBackend, SCENARIO_ID
from persona_lab.responses import QUESTIONS, SURVEY_SCENARIO_ID, price_bands
from persona_lab.scenarios import CHOICES
from persona_lab.survey import PREDECESSOR_DOMAINS, QUESTION_INFO, SURVEY_DOMAINS, SURVEY_QUESTIONS, missing_fields


class SurveyTests(unittest.TestCase):
    def setUp(self):
        persona = Persona('person-id', 'uuid-secret', {}, {'uuid': 'uuid-secret', 'age': 32,
                          'persona': 'macOS에서 매일 메모를 검색한다.', 'professional_persona': '별도 미사용 서술'}, 'hash-secret', {}, {}, {})
        product = {'id': 'item-secret', 'name': '메모 도구',
                   'intro': '검색과 태그로 메모를 정리합니다.',
                   'document': '## 주요 기능\n검색과 태그로 메모를 정리합니다.\n가격: 900 JPY 일시불',
                   'price': {'amount_minor': 2000, 'currency': 'JPY', 'billing': 'one_time'},
                   'price_state': 'paid', 'price_origin': 'explicit',
                   'valuation_unit': {'currency': 'JPY', 'billing': 'one_time'}, 'valuation_bands': price_bands('JPY')}
        self.job = Job(0, 'job-secret', persona, product, copy.deepcopy(SURVEY_QUESTIONS[0]), 0, 123,
                       {'id': SURVEY_SCENARIO_ID, 'initial_state_id': 'initial-v1', 'events': []}, {})
        self.backend = ClefBackend(revision='model-sha', runtime_revision='runtime-sha', survey=True)

    def stage(self, domain, **kwargs):
        question = copy.deepcopy(next(question for question in SURVEY_QUESTIONS if question['domain'] == domain))
        return replace(self.job, question=question, **kwargs)

    @staticmethod
    def envelope(body, choice=None):
        key, question = next(iter(body['questions'].items()))
        options = list(question['criteria'])
        choice = choice or options[0]
        return {'model': 'clef-flash', 'answers': {key: {'type': 'choice', 'choice': choice,
                'probabilities': {option: int(option == choice) for option in options}}},
                'usage': {'input_tokens': 100, 'output_tokens': 0}}

    def test_eight_stage_http_contract_price_blindness_and_all_final_dependencies(self):
        self.assertEqual(SURVEY_DOMAINS, ('need', 'understanding', 'usage', 'alternatives', 'trust', 'onboarding', 'fair_price', 'purchase'))
        self.assertTrue(self.backend.backend_id.endswith(':survey-choice-v1'))
        assessments, requests = {}, []

        def reply(request, **kwargs):
            body = json.loads(request.data)
            if request.full_url.endswith('/tokenize'):
                return io.BytesIO(json.dumps({'tokens': [1] * 1000}).encode())
            self.assertTrue(request.full_url.endswith('/v1/systemone'))
            requests.append(body)
            return io.BytesIO(json.dumps(self.envelope(body)).encode())

        with patch('urllib.request.urlopen', side_effect=reply):
            for question in SURVEY_QUESTIONS:
                domain = question['domain']
                self.assertEqual(set(question['choices']), CHOICES[domain])
                self.assertTrue(QUESTION_INFO[domain]['title'])
                job = self.stage(domain, assessments=copy.deepcopy(assessments))
                body = self.backend.request_body(job)
                state = json.loads(body['state'])
                self.assertNotIn('secret', body['state'])
                self.assertNotIn('professional_persona', state['persona'])
                self.assertEqual(set(body['questions']['decision']['criteria']), set(question['choices']) - {'not_run'})
                if domain in PREDECESSOR_DOMAINS:
                    self.assertNotIn('price', state['product'])
                    self.assertNotIn('900', state['product']['document'])
                    self.assertNotIn('offer', state)
                    self.assertNotIn('prior_assessments', state)
                    changed = replace(job, product={**job.product, 'price': {**job.product['price'], 'amount_minor': 2000000},
                                                   'document': job.product['document'].replace('900', '2000000')})
                    self.assertEqual(body, self.backend.request_body(changed))
                else:
                    self.assertEqual(set(state['prior_assessments']), set(PREDECESSOR_DOMAINS))
                    self.assertEqual(state['offer']['amount_minor'], 2000)
                    self.assertEqual(state['prior_assessments']['fair_price']['band'], price_bands('JPY')[0])
                    for stage in PREDECESSOR_DOMAINS:
                        self.assertTrue(state['prior_assessments'][stage]['label'])
                    for stage in PREDECESSOR_DOMAINS:
                        incomplete = {key: value for key, value in assessments.items() if key != stage}
                        with self.assertRaises(DependencyError):
                            self.backend.decide(replace(job, assessments=incomplete))
                result = self.backend.decide(job)
                validate_decision(result, job)
                self.assertIsNone(result.valuation)
                self.assertEqual(result.reason, '')
                if domain == 'purchase':
                    self.assertTrue({f'assessments.{stage}' for stage in PREDECESSOR_DOMAINS} <= set(result.evidence_refs))
                assessments[domain] = {'choice': result.choice, 'job_id': f'{domain}-secret', 'reason': 'untrusted generated prose'}
        self.assertEqual(len(requests), 8)
        self.assertEqual(self.backend.metrics['completion_tokens'], 0)
        final = self.stage('purchase', assessments=assessments)
        repeated = replace(final, job_id='changed', ordinal=5, seed=999, repeat=7,
                           assessments={key: {**value, 'job_id': 'changed'} for key, value in assessments.items()})
        self.assertEqual(self.backend.request_body(final), self.backend.request_body(repeated))

    def test_new_stage_unknown_followup_and_auxiliary_failure_keep_primary(self):
        job = self.stage('trust')
        events = []
        self.backend.audit = lambda action, identifier, payload: events.append((action, identifier, payload)) or len(events)
        for fail_auxiliary in (False, True):
            with self.subTest(fail_auxiliary=fail_auxiliary):
                bodies = []
                def reply(request, **kwargs):
                    body = json.loads(request.data)
                    bodies.append(body)
                    if 'missing_information' in body['questions']:
                        self.assertEqual(set(body['questions']['missing_information']['criteria']), set(missing_fields('trust')))
                        self.assertIn('신뢰', body['questions']['missing_information']['instructions'])
                        if fail_auxiliary:
                            raise OSError('missing information classifier unavailable')
                        answer = self.envelope(body, 'privacy_terms')
                    else:
                        answer = self.envelope(body, 'unknown')
                    return io.BytesIO(json.dumps(answer).encode())
                with patch('urllib.request.urlopen', side_effect=reply):
                    result = self.backend.decide(job)
                self.assertEqual(result.choice, 'unknown')
                self.assertEqual(result.option_probabilities['unknown'], 1)
                self.assertEqual(result.evidence_semantics, 'supplied_input_only')
                self.assertEqual(bodies[0]['state'], bodies[1]['state'])
                if fail_auxiliary:
                    self.assertEqual(result.missing_information, ())
                    self.assertEqual(result.diagnostic_error['type'], 'OSError')
                    self.assertIn('missing_information_failed', result.reason_codes)
                else:
                    self.assertEqual(result.missing_information, ('자료 저장과 권한 조건',))
                    self.assertIsNone(result.diagnostic_error)
                validate_decision(result, job)
        self.assertEqual([event[0] for event in events], ['start', 'finish'] * 4)

    def test_frozen_three_stage_requests_and_backend_fingerprint_are_unchanged(self):
        backend = ClefBackend(revision='model-sha', runtime_revision='runtime-sha')
        self.assertEqual(backend.backend_id, 'llama-cpp:clef-flash:model-sha:runtime-sha:finite-choice-v1')
        expected = ('34696da166f9ff1514b483db965f7dcbac3a2c3d956af186c2b6c8256544437a',
                    '202bc5e203e08eb1152a0d0a2f65e3189fc9a5db50c3cab0b19fce63322c31b8',
                    '5876dbb9ba23e0aa8baaa77ab3e819eeaf08b8534cb9c29bdcd7ea09281337b7')
        assessments = {'usage': {'job_id': 'usage-secret', 'choice': 'use', 'reason': 'free prose'},
                       'fair_price': {'job_id': 'fair-secret', 'choice': 'price_1'}}
        for question, fingerprint in zip(QUESTIONS, expected):
            job = replace(self.job, scenario={**self.job.scenario, 'id': SCENARIO_ID}, question=copy.deepcopy(question), assessments=assessments)
            body = backend.request_body(job)
            self.assertEqual(hashlib.sha256(canonical(body).encode()).hexdigest(), fingerprint)


if __name__ == '__main__':
    unittest.main()
