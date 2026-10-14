"""Typed predecessor history and frozen seven-question Clef schemas."""
import copy
import io
import json
import unittest
from dataclasses import replace
from unittest.mock import patch

from persona_lab.contracts import ContractError, DependencyError, Job, Persona, validate_decision, validate_experiment
from persona_lab.finite_decision import ClefBackend, GROUPED_PROTOCOL_V2, PRICE_HISTORY_PROTOCOL
from persona_lab.responses import SURVEY_V3_SCENARIO_ID, SURVEY_V4_SCENARIO_ID, price_bands
from persona_lab.survey import (STAGED_BASE_DOMAINS, STAGED_PROTOCOL, SURVEY_HISTORY_PROTOCOL,
    SURVEY_V3_QUESTIONS, SURVEY_V4_DOMAINS, SURVEY_V4_QUESTIONS)


class SurveyV4Tests(unittest.TestCase):
    def setUp(self):
        self.persona = Persona('person-id', 'uuid-1', {}, {'uuid': 'uuid-1', 'age': 32,
            'persona': '매일 회의 메모를 검색하며 macOS를 사용한다.'}, 'hash', {}, {}, {})
        self.product = {'id': 'item-1', 'name': '메모 도구', 'features': [],
            'intro': '메모를 검색하고 태그를 붙인다.',
            'document': '메모를 검색하고 태그를 붙인다.\n가격: 900 JPY 일시불',
            'price': {'amount_minor': 2000, 'currency': 'JPY', 'billing': 'one_time'},
            'valuation_unit': {'currency': 'JPY', 'billing': 'one_time'},
            'valuation_bands': price_bands('JPY')}
        self.scenario = {'id': SURVEY_V4_SCENARIO_ID, 'initial_state_id': 'initial-v1', 'events': []}
        self.backend = ClefBackend(survey_version=SURVEY_V4_SCENARIO_ID,
            inference_protocol=STAGED_PROTOCOL, survey_questions=copy.deepcopy(SURVEY_V4_QUESTIONS))
        self.jobs = [Job(index, f'job-{index}', self.persona, copy.deepcopy(self.product), copy.deepcopy(question),
            0, 17, self.scenario, {}) for index, question in enumerate(SURVEY_V4_QUESTIONS)]
        self.calls = []

    def history(self, count, unknown=False):
        records = [{'domain': question['domain'], 'job_id': f'prior-{index}',
                    'choice': question['choices'][0], 'status': 'ok', 'missing_information': []}
                   for index, question in enumerate(SURVEY_V4_QUESTIONS[:count])]
        if unknown:
            records[0].update(choice='unknown', status='insufficient_information',
                              missing_information=['구체적인 활용 목적'])
        return {'protocol': SURVEY_HISTORY_PROTOCOL, 'persona_id': self.persona.persona_id,
                'product_id': self.product['id'], 'repeat': 0, 'records': records}

    def reply(self, request, **kwargs):
        if request.full_url.endswith('/tokenize'):
            return io.BytesIO(json.dumps({'tokens': [1] * 100}).encode())
        body = json.loads(request.data)
        self.calls.append(body)
        answers = {}
        for identifier, question in body['questions'].items():
            choice = next(iter(question['criteria']))
            answers[identifier] = {'type': 'choice', 'choice': choice,
                'probabilities': {option: int(option == choice) for option in question['criteria']}}
        return io.BytesIO(json.dumps({'answers': answers,
            'usage': {'input_tokens': 100, 'output_tokens': 0}}).encode())

    def test_three_requests_have_seven_then_eight_actual_predecessors(self):
        usage = replace(self.jobs[7], survey_history=self.history(7, unknown=True))
        price = replace(self.jobs[8], survey_history=self.history(8, unknown=True))
        with patch('urllib.request.urlopen', side_effect=self.reply):
            base = self.backend.decide_batch(self.jobs[:7])
            for job in self.jobs[:7]:
                validate_decision(base[job.job_id], job)
            for job in (usage, price):
                validate_decision(self.backend.decide(job), job)
        self.assertEqual([len(body['questions']) for body in self.calls], [7, 1, 1])
        states = [json.loads(body['state']) for body in self.calls]
        self.assertNotIn('survey_decision_history', states[0])
        for state, count in zip(states[1:], (7, 8)):
            supplied = state['survey_decision_history']
            self.assertEqual([record['domain'] for record in supplied['records']], list(SURVEY_V4_DOMAINS[:count]))
            self.assertEqual(supplied['records'][0]['choice'], 'unknown')
            self.assertEqual(supplied['records'][0]['missing_information'], ['구체적인 활용 목적'])
            self.assertNotIn('job_id', json.dumps(supplied))
            self.assertNotIn('person-id', json.dumps(supplied))
            self.assertNotIn('item-1', json.dumps(supplied))
        for state in states:
            self.assertNotIn('offer', state)
            self.assertNotIn('price', state['product'])
            self.assertNotIn('900', state['product']['document'])
        self.assertNotIn('valuation_bands', states[0])
        self.assertNotIn('valuation_bands', states[1])
        self.assertIn('valuation_bands', states[2])
        self.assertEqual(self.backend.batch_limit, 7)
        self.assertTrue(self.backend.backend_id.endswith(':survey-choice-v4:survey-staged-v1'))
        body = self.backend.request_body(price)
        changed = replace(price, product={**price.product, 'price': {**price.product['price'], 'amount_minor': 990000},
            'document': price.product['document'].replace('900', '990000')})
        self.assertEqual(body, self.backend.request_body(changed))
        self.assertNotIn('모든 질문은 원문으로 독립 평가', body['questions']['decision']['instructions'])

    def test_history_rejects_wrong_identity_order_missing_and_execution_error(self):
        for protocol in (None, GROUPED_PROTOCOL_V2):
            with self.subTest(protocol=protocol), self.assertRaises(ContractError):
                ClefBackend(survey_version=SURVEY_V4_SCENARIO_ID, inference_protocol=protocol)
            spec = {'schema_version': '0.1', 'experiment_id': 'survey-v4-test', 'mode': 'independent_comparison',
                'panel': {'selection': 'all'}, 'seed': 17, 'repeats': 1, 'batch_size': 7, 'assumptions': {},
                'scenario': copy.deepcopy(self.scenario), 'products': [copy.deepcopy(self.product)],
                'questions': copy.deepcopy(SURVEY_V4_QUESTIONS)}
            if protocol is not None:
                spec['inference_protocol'] = protocol
            with self.assertRaises(ContractError):
                validate_experiment(spec)
        usage = replace(self.jobs[7], survey_history=self.history(7))
        invalid = []
        for key, value in (('persona_id', 'other'), ('product_id', 'other'), ('repeat', 1)):
            invalid.append({**self.history(7), key: value})
        reordered = self.history(7)
        reordered['records'][0], reordered['records'][1] = reordered['records'][1], reordered['records'][0]
        invalid.extend((reordered, self.history(6)))
        bad_status = self.history(7)
        bad_status['records'][0]['status'] = 'insufficient_information'
        invalid.append(bad_status)
        for history in invalid:
            with self.subTest(history=history), self.assertRaises(ContractError):
                self.backend.request_body(replace(usage, survey_history=history))
        with self.assertRaises(ContractError):
            self.backend.request_body(self.jobs[7])
        with self.assertRaises(ContractError):
            self.backend.request_body(replace(self.jobs[8], survey_history=self.history(7)))
        with self.assertRaises(ContractError):
            self.backend.request_body(replace(self.jobs[0], survey_history=self.history(7)))
        error = self.history(7)
        error['records'][0].update(choice='error', status='backend_error')
        with patch('urllib.request.urlopen') as request, self.assertRaises(DependencyError):
            self.backend.decide(replace(usage, survey_history=error))
        request.assert_not_called()

    def test_base_retry_keeps_full_schema_and_calibration_stays_separate(self):
        full, _ = self.backend._grouped_base_body(self.jobs[:7])
        retried, _ = self.backend._grouped_base_body([self.jobs[2]])
        self.assertEqual(full, retried)
        self.assertEqual(len(retried['questions']), len(STAGED_BASE_DOMAINS))
        with self.assertRaises(ContractError):
            self.backend.decide_batch(self.jobs)
        with patch.object(self.backend, '_preflight_bodies') as preflight:
            self.backend.preflight_planned_stage([self.jobs[7]])
        preflight.assert_not_called()
        calibration = replace(self.jobs[-1], assumptions={'evaluation_phase': 'price_calibration'})
        old = ClefBackend(survey_version=SURVEY_V3_SCENARIO_ID, inference_protocol=GROUPED_PROTOCOL_V2)
        old_job = replace(calibration, scenario={**calibration.scenario, 'id': SURVEY_V3_SCENARIO_ID},
                          question=copy.deepcopy(SURVEY_V3_QUESTIONS[-1]), assumptions={})
        self.assertEqual(old.request_body(old_job), self.backend.request_body(calibration))
        history = {'protocol': PRICE_HISTORY_PROTOCOL, 'persona_id': self.persona.persona_id,
            'valuation_unit': self.product['valuation_unit'], 'records': [
                {'round': 0, 'phase': 'broad', 'job_id': 'pilot-0', 'status': 'ok',
                 'interval': {'low_minor': 100, 'high_minor': 9999}}]}
        self.assertEqual(old.request_body(replace(old_job, calibration_history=history)),
                         self.backend.request_body(replace(calibration, calibration_history=history)))
        with self.assertRaises(ContractError):
            self.backend.request_body(replace(calibration, survey_history=self.history(8)))
        with self.assertRaises(ContractError):
            self.backend.request_body(replace(self.jobs[8], survey_history=self.history(8), calibration_history=history))
        with self.assertRaises(ContractError):
            old.request_body(replace(old_job, survey_history=self.history(8)))


if __name__ == '__main__':
    unittest.main()
