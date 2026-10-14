"""Two-call willingness-to-pay surveys retain separate frozen v2 semantics."""
import copy
import io
import json
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from persona_lab.contracts import ContractError, Job, Persona, validate_decision, validate_experiment
from persona_lab.finite_decision import ClefBackend, GROUPED_PROTOCOL, GROUPED_PROTOCOL_V2
from persona_lab.responses import SURVEY_V2_SCENARIO_ID, SURVEY_V3_SCENARIO_ID, price_bands
from persona_lab.runner import run
from persona_lab.survey import SURVEY_V2_QUESTIONS, SURVEY_V3_DOMAINS, SURVEY_V3_QUESTIONS, question_info


class SurveyV3Tests(unittest.TestCase):
    def setUp(self):
        self.persona = Persona('person-id', 'uuid-1', {}, {'uuid': 'uuid-1', 'age': 32,
            'persona': '매일 회의 메모를 검색하며 macOS를 사용한다.'}, 'hash', {}, {}, {})
        self.product = {'id': 'item-1', 'name': '메모 도구', 'features': [],
            'intro': '메모를 검색하고 태그를 붙인다.',
            'document': '메모를 검색하고 태그를 붙인다.\n가격: 900 JPY 일시불',
            'price': {'amount_minor': 2000, 'currency': 'JPY', 'billing': 'one_time'},
            'valuation_unit': {'currency': 'JPY', 'billing': 'one_time'}, 'valuation_bands': price_bands('JPY')}
        self.scenario = {'id': SURVEY_V3_SCENARIO_ID, 'initial_state_id': 'initial-v1', 'events': []}
        self.backend = ClefBackend(survey_version=SURVEY_V3_SCENARIO_ID,
            inference_protocol=GROUPED_PROTOCOL_V2, survey_questions=copy.deepcopy(SURVEY_V3_QUESTIONS))
        self.jobs = [Job(index, f'job-{index}', self.persona, copy.deepcopy(self.product), copy.deepcopy(question),
            0, 17, self.scenario, {}) for index, question in enumerate(SURVEY_V3_QUESTIONS)]
        self.calls = []

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

    def test_two_calls_store_nine_results_keep_price_blind_and_preserve_v2(self):
        spec = {'schema_version': '0.1', 'experiment_id': 'survey-v3-test', 'mode': 'independent_comparison',
            'panel': {'selection': 'all'}, 'seed': 17, 'repeats': 1, 'batch_size': 9, 'assumptions': {},
            'scenario': copy.deepcopy(self.scenario), 'products': [copy.deepcopy(self.product)],
            'questions': copy.deepcopy(SURVEY_V3_QUESTIONS), 'inference_protocol': GROUPED_PROTOCOL_V2}
        source = {'schema_version': '0.1', 'source_id': 'survey-test', 'version': 'authored-v1',
            'url': 'local:test', 'license_id': 'LicenseRef-Test', 'license_url': 'local:test',
            'origin': 'project_synthetic_fixture'}
        with tempfile.TemporaryDirectory() as temporary:
            path, store = Path(temporary) / 'people.jsonl', Path(temporary) / 'run.sqlite'
            path.write_text(json.dumps(self.persona.raw, ensure_ascii=False) + '\n')
            with patch('urllib.request.urlopen', side_effect=self.reply):
                status = run(path, source, spec, store, self.backend)
            self.assertEqual((status['cursor'], status['total'], status['backend_errors']), (9, 9, 0))
            with sqlite3.connect(store) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM model_calls').fetchone()[0], 2)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM model_call_jobs').fetchone()[0], 9)
                self.assertEqual(tuple(row[0] for row in db.execute('SELECT domain FROM results ORDER BY ordinal')), SURVEY_V3_DOMAINS)
        self.assertEqual([len(body['questions']) for body in self.calls], [8, 1])
        self.assertEqual(self.backend.batch_limit, 9)
        self.assertNotIn('purchase', SURVEY_V3_DOMAINS)
        fair = self.jobs[-1]
        body = self.backend.request_body(fair)
        changed = replace(fair, product={**fair.product, 'price': {**fair.product['price'], 'amount_minor': 990000},
            'document': fair.product['document'].replace('900', '990000')}, assessments={'usage': {'choice': 'error'}})
        self.assertEqual(body, self.backend.request_body(changed))
        state = json.loads(body['state'])
        self.assertNotIn('offer', state)
        self.assertNotIn('prior_assessments', state)
        self.assertNotIn('900', state['product']['document'])
        self.assertIn('최대 가격이 속한 구간', body['questions']['decision']['instructions'])
        self.assertIn('최대 지불 의향 가격', body['questions']['decision']['criteria']['price_0'])
        self.assertEqual(question_info('fair_price', SURVEY_V3_SCENARIO_ID)['title'], '최대 지불 의향 가격대')

        old = ClefBackend(survey_version=SURVEY_V2_SCENARIO_ID, inference_protocol=GROUPED_PROTOCOL,
            survey_questions=copy.deepcopy(SURVEY_V2_QUESTIONS))
        old_jobs = [replace(self.jobs[0], ordinal=index, job_id=f'old-{index}', question=question,
            scenario={**self.scenario, 'id': SURVEY_V2_SCENARIO_ID}) for index, question in enumerate(SURVEY_V2_QUESTIONS)]
        self.calls = []
        with patch('urllib.request.urlopen', side_effect=self.reply):
            decisions = old.decide_batch(old_jobs)
        for job in old_jobs:
            validate_decision(decisions[job.job_id], job)
        self.assertEqual([len(call['questions']) for call in self.calls], [8, 1, 1])
        self.assertNotEqual(self.backend.backend_id, old.backend_id)
        self.assertTrue(self.backend.backend_id.endswith(':survey-choice-v3:survey-grouped-v2'))
        self.assertTrue(old.backend_id.endswith(':survey-choice-v2:survey-grouped-v1'))
        self.assertIn('선택한 구간은 지불할 최대가격이나 정확한 추정 금액이 아닙니다.',
            old.request_body(old_jobs[-2])['questions']['decision']['instructions'])
        with self.assertRaises(ContractError):
            ClefBackend(survey_version=SURVEY_V3_SCENARIO_ID, inference_protocol=GROUPED_PROTOCOL)
        with self.assertRaises(ContractError):
            ClefBackend(survey_version=SURVEY_V3_SCENARIO_ID, inference_protocol=GROUPED_PROTOCOL_V2,
                survey_questions=SURVEY_V2_QUESTIONS)
        with self.assertRaises(ContractError):
            validate_experiment({**spec, 'inference_protocol': GROUPED_PROTOCOL})
        with self.assertRaisesRegex(ContractError, 'frozen catalog'):
            self.backend.decide_batch([replace(fair, question={**fair.question, 'prompt': '수정한 문항'})])

    def test_missing_price_grid_and_unknown_diagnostic_keep_distinct_statuses(self):
        fair = self.jobs[-1]
        absent = replace(fair, product={**fair.product, 'valuation_bands': []})
        with patch('urllib.request.urlopen') as request:
            skipped = self.backend.decide(absent)
        request.assert_not_called()
        self.assertEqual((skipped.choice, skipped.status), ('not_run', 'not_run'))
        validate_decision(skipped, absent)

        def unknown(request, **kwargs):
            body = json.loads(request.data)
            self.calls.append(body)
            key, question = next(iter(body['questions'].items()))
            choice = 'value_basis' if key == 'missing_information' else 'unknown'
            envelope = {'answers': {key: {'type': 'choice', 'choice': choice,
                'probabilities': {option: int(option == choice) for option in question['criteria']}}},
                'usage': {'input_tokens': 100, 'output_tokens': 0}}
            return io.BytesIO(json.dumps(envelope).encode())
        with patch.object(self.backend, 'preflight'), patch('urllib.request.urlopen', side_effect=unknown):
            decision = self.backend.decide(fair)
        validate_decision(decision, fair)
        self.assertEqual((decision.choice, decision.status), ('unknown', 'insufficient_information'))
        self.assertEqual(decision.missing_information, ('개인 선호와 추가 가치의 판단 근거',))
        self.assertIn('최대 지불 의향 가격대', self.calls[-1]['questions']['missing_information']['instructions'])
        self.assertEqual(self.calls[0]['state'], self.calls[1]['state'])


if __name__ == '__main__':
    unittest.main()
