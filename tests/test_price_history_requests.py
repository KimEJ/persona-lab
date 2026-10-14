"""Calibration history is explicit, persona-bound and isolated from normal surveys."""
import copy
import json
import unittest
from dataclasses import replace

from persona_lab.contracts import ContractError, Job, Persona, canonical, validate_decision
from persona_lab.finite_decision import ClefBackend, PRICE_HISTORY_PROTOCOL, SURVEY_V2_POLICY, SURVEY_V3_POLICY
from persona_lab.responses import SURVEY_V2_SCENARIO_ID, SURVEY_V3_SCENARIO_ID, price_bands
from persona_lab.survey import SURVEY_V2_QUESTIONS, SURVEY_V3_QUESTIONS, survey_meanings


class PriceHistoryRequestTests(unittest.TestCase):
    def setUp(self):
        persona = Persona('person-1', 'uuid-1', {}, {'uuid': 'uuid-1', 'age': 32,
            'persona': '매일 회의 메모를 기록한다.'}, 'hash', {}, {}, {})
        product = {'id': 'notebook', 'name': '줄노트', 'features': [], 'intro': 'A5 줄노트 96쪽.',
            'document': 'A5 줄노트 96쪽.', 'price': None,
            'valuation_unit': {'currency': 'JPY', 'billing': 'one_time'},
            'valuation_bands': price_bands('JPY')}
        question = next(question for question in SURVEY_V3_QUESTIONS if question['domain'] == 'fair_price')
        self.job = Job(0, 'current-job', persona, product, copy.deepcopy(question), 0, 17,
            {'id': SURVEY_V3_SCENARIO_ID, 'initial_state_id': 'initial-v1', 'events': []}, {})
        self.backend = ClefBackend(survey_version=SURVEY_V3_SCENARIO_ID)
        self.history = {'protocol': PRICE_HISTORY_PROTOCOL, 'persona_id': persona.persona_id,
            'valuation_unit': copy.deepcopy(product['valuation_unit']), 'records': [
                {'round': 0, 'phase': 'broad', 'job_id': 'prior-0', 'status': 'ok',
                 'interval': {'low_minor': 100, 'high_minor': 9999}},
                {'round': 1, 'phase': 'refinement', 'job_id': 'prior-1', 'status': 'unknown'},
                {'round': 2, 'phase': 'contract', 'job_id': 'prior-2', 'status': 'error'},
            ]}

    def expected_plain_body(self, job, policy):
        state = {'persona': {key: value for key, value in job.persona.raw.items() if key != 'uuid'},
            'product': {'name': job.product['name'], 'document': job.product['document']}}
        if job.question['domain'] == 'fair_price':
            state.update(valuation_unit=job.product['valuation_unit'], valuation_bands=job.product['valuation_bands'])
        choices = [choice for choice in job.question['choices'] if choice != 'not_run']
        meanings = survey_meanings(job)
        return {'model': 'clef-flash', 'state': canonical(state), 'questions': {'decision': {
            'type': 'choice', 'instructions': policy + ' ' + job.question['prompt'],
            'criteria': {choice: meanings[choice] for choice in choices},
        }}}

    def test_serializes_numeric_history_and_replaces_independent_policy(self):
        plain = self.backend.request_body(self.job)
        job = replace(self.job, calibration_history=self.history)
        body = self.backend.request_body(job)
        state = json.loads(body['state'])
        supplied = state.pop('price_decision_history')
        self.assertEqual(state, json.loads(plain['state']))
        self.assertEqual(supplied, {'protocol': PRICE_HISTORY_PROTOCOL,
            'valuation_unit': self.history['valuation_unit'],
            'records': [{key: value for key, value in record.items() if key != 'job_id'}
                        for record in self.history['records']]})
        self.assertNotIn('persona_id', supplied)
        self.assertTrue(all('job_id' not in record for record in supplied['records']))
        self.assertNotIn('interval', supplied['records'][1])
        self.assertNotIn('interval', supplied['records'][2])
        self.assertEqual(body['questions']['decision']['criteria'], plain['questions']['decision']['criteria'])
        instructions = body['questions']['decision']['instructions']
        self.assertNotIn('모든 질문은 원문으로 독립 평가하며 다른 질문의 답변은 제공되지 않습니다.', instructions)
        self.assertIn('현재 가격 구간의 해상도로 앞선 평가를 세분화', instructions)
        self.assertIn('이전 응답은 모델의 판단이며 인물의 사실이 아닙니다.', instructions)
        self.assertIn('이전 가격 구간을 벗어나도록 판단을 수정해야 하면 unknown을 선택', instructions)
        self.assertIn(self.job.question['prompt'], instructions)
        choice = 'price_1'
        probabilities = {option: int(option == choice) for option in body['questions']['decision']['criteria']}
        decision = self.backend._decision(job, choice, probabilities)
        validate_decision(decision, job)
        self.assertIn('calibration_history', decision.evidence_refs)
        self.assertEqual(decision.evidence_semantics, 'supplied_input_only')
        self.assertNotIn('calibration_history', self.backend._decision(self.job, choice, probabilities).evidence_refs)
        supplied['records'][0]['interval']['low_minor'] = 999
        self.assertEqual(self.history['records'][0]['interval']['low_minor'], 100)
        open_history = copy.deepcopy(self.history)
        open_history['records'][0]['interval']['high_minor'] = None
        self.assertIsNone(json.loads(self.backend.request_body(replace(self.job,
            calibration_history=open_history))['state'])['price_decision_history']['records'][0]['interval']['high_minor'])

    def test_plain_main_and_legacy_bodies_remain_unchanged_and_reject_history(self):
        self.assertIsNone(self.job.calibration_history)
        self.assertEqual(self.backend.request_body(self.job), self.expected_plain_body(self.job, SURVEY_V3_POLICY))
        base = replace(self.job, question=copy.deepcopy(SURVEY_V3_QUESTIONS[0]))
        self.assertEqual(self.backend.request_body(base), self.expected_plain_body(base, SURVEY_V3_POLICY))
        with self.assertRaisesRegex(ContractError, 'v3 price calibration'):
            self.backend.request_body(replace(base, calibration_history=self.history))
        legacy = replace(self.job, scenario={**self.job.scenario, 'id': SURVEY_V2_SCENARIO_ID},
            question=copy.deepcopy(next(question for question in SURVEY_V2_QUESTIONS if question['domain'] == 'fair_price')))
        old_backend = ClefBackend(survey_version=SURVEY_V2_SCENARIO_ID)
        self.assertEqual(old_backend.request_body(legacy), self.expected_plain_body(legacy, SURVEY_V2_POLICY))
        with self.assertRaisesRegex(ContractError, 'v3 price calibration'):
            old_backend.request_body(replace(legacy, calibration_history=self.history))

    def test_invalid_history_is_rejected_before_serialization(self):
        invalid = []
        for key, value in [('protocol', 'price-calibration-history-v0'), ('persona_id', 'other-person'),
                           ('valuation_unit', {'currency': 'USD', 'billing': 'one_time'}),
                           ('valuation_unit', {'currency': 'JPY', 'billing': 'monthly'}),
                           ('records', []), ('records', self.history['records'] * 2)]:
            history = copy.deepcopy(self.history)
            history[key] = value
            invalid.append(history)
        for key, value in [('status', 'pending'), ('status', []), ('round', -1), ('round', 3),
                           ('round', True), ('phase', 'other'), ('phase', []), ('job_id', '')]:
            history = copy.deepcopy(self.history)
            history['records'][0][key] = value
            invalid.append(history)
        for interval in [{}, {'low_minor': -1, 'high_minor': 9}, {'low_minor': True, 'high_minor': 9},
                         {'low_minor': 10, 'high_minor': 9}, {'low_minor': 0, 'high_minor': '9'},
                         {'low_minor': 0, 'high_minor': False}]:
            history = copy.deepcopy(self.history)
            history['records'][0]['interval'] = interval
            invalid.append(history)
        history = copy.deepcopy(self.history)
        history['records'][1]['round'] = 0
        invalid.append(history)
        history = copy.deepcopy(self.history)
        history['records'][1]['interval'] = {'low_minor': 0, 'high_minor': 999}
        invalid.append(history)
        history = copy.deepcopy(self.history)
        history['records'][2]['message'] = 'backend error text'
        invalid.append(history)
        for history in invalid:
            with self.subTest(history=history), self.assertRaises(ContractError):
                self.backend.request_body(replace(self.job, calibration_history=history))


if __name__ == '__main__':
    unittest.main()
