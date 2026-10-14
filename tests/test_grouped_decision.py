"""Grouped survey calls retain all ten measurements and their individual errors."""

import copy
import io
import json
import unittest
from dataclasses import replace
from unittest.mock import patch

from persona_lab.contracts import ContractError, Decision, Job, Persona, validate_decision
from persona_lab.finite_decision import ClefBackend, GROUPED_PROTOCOL
from persona_lab.responses import SURVEY_V2_SCENARIO_ID, price_bands
from persona_lab.survey import SURVEY_V2_QUESTIONS


class GroupedDecisionTests(unittest.TestCase):
    def setUp(self):
        self.catalog = copy.deepcopy(SURVEY_V2_QUESTIONS)
        persona = Persona('person-1', 'uuid-1', {}, {'age': 32, 'persona': '毎日メモを書き、検索している。'}, 'hash-1', {}, {}, {})
        product = {'id': 'product-1', 'name': '메모 도구', 'intro': '메모 검색과 태그',
                   'document': '## 기능\n메모를 검색하고 태그를 붙인다.\n가격: 900 JPY 일시불',
                   'price': {'amount_minor': 2000, 'currency': 'JPY', 'billing': 'one_time'},
                   'valuation_unit': {'currency': 'JPY', 'billing': 'one_time'}, 'valuation_bands': price_bands('JPY')}
        self.jobs = [Job(index, f'job-{index}', persona, copy.deepcopy(product), question, 0, 17,
                         {'id': SURVEY_V2_SCENARIO_ID, 'initial_state_id': 'initial-v1', 'events': []}, {})
                     for index, question in enumerate(self.catalog)]
        self.backend = self.make_backend()
        self.calls, self.tokenizations, self.audits = [], [], []
        def audit(action, identifier, value):
            self.audits.append((action, identifier, value))
            return len(self.audits)
        self.backend.audit = audit

    def make_backend(self, **kwargs):
        return ClefBackend(revision='model-sha', runtime_revision='runtime-sha',
                           survey_version=SURVEY_V2_SCENARIO_ID, inference_protocol=GROUPED_PROTOCOL,
                           survey_questions=self.catalog, **kwargs)

    @staticmethod
    def envelope(body, selections=None):
        selections = selections or {}
        answers = {}
        for identifier, question in body['questions'].items():
            choice = selections.get(identifier, next(iter(question['criteria'])))
            answers[identifier] = {'type': 'choice', 'choice': choice,
                                   'probabilities': {option: int(option == choice) for option in question['criteria']}}
        return {'answers': answers, 'usage': {'input_tokens': 100, 'output_tokens': 0}}

    def reply(self, request, **kwargs):
        body = json.loads(request.data)
        if request.full_url.endswith('/tokenize'):
            self.tokenizations.append(body)
            return io.BytesIO(json.dumps({'tokens': [1] * 100}).encode())
        self.assertTrue(request.full_url.endswith('/v1/systemone'))
        self.calls.append(body)
        return io.BytesIO(json.dumps(self.envelope(body)).encode())

    def assert_decisions(self, outcomes, jobs=None):
        jobs = self.jobs if jobs is None else jobs
        self.assertEqual(set(outcomes), {job.job_id for job in jobs})
        for job in jobs:
            validate_decision(outcomes[job.job_id], job)

    def test_paid_three_calls_retain_ten_decisions_and_price_isolation(self):
        with patch('urllib.request.urlopen', side_effect=self.reply):
            outcomes = self.backend.decide_batch(self.jobs)
        self.assert_decisions(outcomes)
        self.assertEqual(len(self.calls), 3)
        base, fair, purchase = self.calls
        self.assertEqual(list(base['questions']), [question['id'] for question in self.catalog[:8]])
        base_state = json.loads(base['state'])
        self.assertEqual(set(base_state), {'persona', 'product'})
        self.assertNotIn('900', base['state'])
        self.assertNotIn('2000', base['state'])
        self.assertNotIn('valuation', json.dumps(base_state))
        self.assertIn('valuation_bands', json.loads(fair['state']))
        self.assertNotIn('offer', json.loads(fair['state']))
        self.assertEqual(json.loads(purchase['state'])['offer']['amount_minor'], 2000)
        self.assertNotIn('valuation_bands', json.loads(purchase['state']))
        self.assertNotIn('prior_assessments', purchase['state'])
        self.assertEqual(self.backend.metrics, {'requests': 3, 'prompt_tokens': 300, 'completion_tokens': 0})
        starts = [value for event, _, value in self.audits if event == 'start']
        self.assertEqual(starts[0]['job_ids'], [job.job_id for job in self.jobs[:8]])
        self.assertNotIn('job_ids', starts[1])
        self.assertNotIn('job_ids', starts[2])
        instructions = [question['instructions'] for question in base['questions'].values()]
        self.assertEqual(sum('공통 평가 원칙' in value for value in instructions), 1)
        self.assertNotIn('모든 질문은 원문으로 독립 평가', ''.join(instructions))
        for job, instruction in zip(self.jobs[:8], instructions):
            self.assertIn(job.question['prompt'], instruction)

    def test_unset_price_uses_two_calls_and_explicit_not_run(self):
        jobs = [replace(job, product={**job.product, 'price': None}) for job in self.jobs]
        with patch('urllib.request.urlopen', side_effect=self.reply):
            outcomes = self.backend.decide_batch(jobs)
        self.assert_decisions(outcomes, jobs)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(outcomes['job-9'].status, 'not_run')

    def test_unknown_fields_share_one_diagnostic_with_individual_mappings(self):
        unknown_ids = [self.catalog[index]['id'] for index in (0, 5)]
        def reply(request, **kwargs):
            if request.full_url.endswith('/tokenize'):
                return self.reply(request, **kwargs)
            body = json.loads(request.data)
            self.calls.append(body)
            if len(body['questions']) == 8:
                result = self.envelope(body, {identifier: 'unknown' for identifier in unknown_ids})
            else:
                self.assertEqual(set(body['questions']), {'missing_' + identifier for identifier in unknown_ids})
                result = self.envelope(body, {'missing_' + unknown_ids[0]: 'usage_goal',
                                              'missing_' + unknown_ids[1]: 'claim_evidence'})
            return io.BytesIO(json.dumps(result).encode())
        with patch('urllib.request.urlopen', side_effect=reply):
            outcomes = self.backend.decide_batch(self.jobs[:8])
        self.assert_decisions(outcomes, self.jobs[:8])
        self.assertEqual(len(self.calls), 2)
        for index, field in ((0, 'usage_goal'), (5, 'claim_evidence')):
            result = outcomes[f'job-{index}']
            self.assertEqual((result.choice, result.status), ('unknown', 'insufficient_information'))
            self.assertEqual(result.option_probabilities['unknown'], 1)
            self.assertIn('missing.' + field, result.reason_codes)
            self.assertTrue(result.missing_information)
        diagnostic_start = [value for event, _, value in self.audits if event == 'start'][1]
        self.assertEqual(diagnostic_start['job_ids'], ['job-0', 'job-5'])
        self.assertEqual(self.calls[0]['state'], self.calls[1]['state'])

    def test_diagnostic_error_preserves_primary_and_valid_other_diagnostics(self):
        unknown_ids = [self.catalog[index]['id'] for index in (0, 5)]
        for failure in ('transport', 'one_answer'):
            with self.subTest(failure=failure):
                backend = self.make_backend()
                def reply(request, **kwargs):
                    if request.full_url.endswith('/tokenize'):
                        return self.reply(request, **kwargs)
                    body = json.loads(request.data)
                    if len(body['questions']) == 8:
                        result = self.envelope(body, {identifier: 'unknown' for identifier in unknown_ids})
                    elif failure == 'transport':
                        raise OSError('classification unavailable')
                    else:
                        result = self.envelope(body)
                        result['answers']['missing_' + unknown_ids[0]]['probabilities'] = {'usage_goal': 1}
                    return io.BytesIO(json.dumps(result).encode())
                with patch('urllib.request.urlopen', side_effect=reply):
                    outcomes = backend.decide_batch(self.jobs[:8])
                self.assert_decisions(outcomes, self.jobs[:8])
                failed = outcomes['job-0']
                self.assertEqual(failed.choice, 'unknown')
                self.assertEqual(failed.option_probabilities['unknown'], 1)
                self.assertEqual(failed.missing_information, ())
                self.assertIn('missing_information_failed', failed.reason_codes)
                self.assertIsNotNone(failed.diagnostic_error)
                if failure == 'one_answer':
                    self.assertTrue(outcomes['job-5'].missing_information)
                    self.assertIsNone(outcomes['job-5'].diagnostic_error)

    def test_invalid_one_primary_answer_does_not_erase_other_measurements(self):
        def reply(request, **kwargs):
            if request.full_url.endswith('/tokenize'):
                return self.reply(request, **kwargs)
            body = json.loads(request.data)
            result = self.envelope(body)
            result['answers'][self.catalog[2]['id']]['probabilities'] = {'clear': 1}
            return io.BytesIO(json.dumps(result).encode())
        with patch('urllib.request.urlopen', side_effect=reply):
            outcomes = self.backend.decide_batch(self.jobs[:8])
        self.assertIsInstance(outcomes['job-2'], ContractError)
        for job in self.jobs[:8]:
            if job.job_id != 'job-2':
                validate_decision(outcomes[job.job_id], job)
        self.assertEqual(self.backend.metrics['prompt_tokens'], 100)

    def test_envelope_errors_fail_the_base_group(self):
        for mutation in ('ids', 'tokens', 'json'):
            with self.subTest(mutation=mutation):
                backend = self.make_backend()
                def reply(request, **kwargs):
                    if request.full_url.endswith('/tokenize'):
                        return self.reply(request, **kwargs)
                    body = json.loads(request.data)
                    result = self.envelope(body)
                    if mutation == 'ids': result['answers'].pop(next(iter(result['answers'])))
                    if mutation == 'tokens': result['usage']['output_tokens'] = 1
                    return io.BytesIO(b'not json' if mutation == 'json' else json.dumps(result).encode())
                with patch('urllib.request.urlopen', side_effect=reply):
                    outcomes = backend.decide_batch(self.jobs[:8])
                self.assertTrue(all(isinstance(outcome, ContractError) for outcome in outcomes.values()))
                self.assertEqual(backend.metrics['requests'], 1)

    def test_retry_subset_keeps_full_schema_and_only_persists_active_results(self):
        with patch('urllib.request.urlopen', side_effect=self.reply):
            self.backend.decide_batch(self.jobs[:8])
            result = self.backend.decide_batch([self.jobs[3]])
        self.assertEqual(self.calls[0], self.calls[1])
        self.assertEqual(set(result), {'job-3'})
        self.assertIsInstance(result['job-3'], Decision)
        start = [value for event, _, value in self.audits if event == 'start'][-1]
        self.assertEqual(start['job_ids'], ['job-3'])

    def test_retry_does_not_diagnose_or_fail_on_inactive_answers(self):
        def reply(request, **kwargs):
            if request.full_url.endswith('/tokenize'):
                return self.reply(request, **kwargs)
            body = json.loads(request.data)
            self.calls.append(body)
            result = self.envelope(body, {question['id']: 'unknown' for question in self.catalog[:8]
                                           if question['id'] != self.jobs[3].question['id']})
            result['answers'][self.jobs[0].question['id']]['probabilities'] = {'unknown': 1}
            return io.BytesIO(json.dumps(result).encode())
        with patch('urllib.request.urlopen', side_effect=reply):
            outcomes = self.backend.decide_batch([self.jobs[3]])
        self.assert_decisions(outcomes, [self.jobs[3]])
        self.assertEqual(len(self.calls), 1)

    def test_frozen_question_and_option_order_survive_caller_changes(self):
        self.catalog[0]['choices'].reverse()
        backend = self.make_backend()
        jobs = [replace(job, question=copy.deepcopy(question)) for job, question in zip(self.jobs, self.catalog)]
        expected = list(self.catalog[0]['choices'])
        self.catalog[0]['choices'].reverse()
        with patch('urllib.request.urlopen', side_effect=self.reply):
            outcomes = backend.decide_batch(jobs[:8])
        self.assert_decisions(outcomes, jobs[:8])
        self.assertEqual(list(self.calls[0]['questions'][jobs[0].question['id']]['criteria']), expected)
        with self.assertRaisesRegex(ContractError, 'frozen catalog'):
            backend.decide_batch([replace(jobs[0], question={**jobs[0].question, 'prompt': 'changed prompt'})])

    def test_distinct_persona_product_and_repeat_do_not_share_a_request(self):
        variants = [self.jobs[:8],
                    [replace(job, job_id='other-person-' + job.job_id,
                             persona=replace(job.persona, persona_id='other-person', uuid='other-uuid')) for job in self.jobs[:8]],
                    [replace(job, job_id='other-product-' + job.job_id,
                             product={**job.product, 'id': 'other-product', 'name': '다른 상품'}) for job in self.jobs[:8]],
                    [replace(job, job_id='other-repeat-' + job.job_id, repeat=1) for job in self.jobs[:8]]]
        jobs = [job for variant in variants for job in variant]
        with patch('urllib.request.urlopen', side_effect=self.reply):
            outcomes = self.backend.decide_batch(jobs)
        self.assert_decisions(outcomes, jobs)
        self.assertEqual(len(self.calls), 4)
        starts = [value for event, _, value in self.audits if event == 'start']
        self.assertEqual([value['job_ids'] for value in starts], [[job.job_id for job in variant] for variant in variants])

    def test_preflight_checks_full_primary_and_worstcase_diagnostic_and_caches_success(self):
        with patch.object(self.backend, '_preflight_bodies') as check:
            self.backend.preflight_batch([self.jobs[3]])
        bodies = check.call_args.args[0]
        self.assertEqual([len(body['questions']) for body in bodies], [8, 8])
        self.assertTrue(all(identifier.startswith('missing_') for identifier in bodies[1]['questions']))
        jobs = [replace(job, product={**job.product, 'document': '긴 상품 문서 ' * 1000}) for job in self.jobs[:8]]
        with patch('urllib.request.urlopen', side_effect=self.reply):
            self.backend.preflight_batch(jobs)
            first_count = len(self.tokenizations)
            self.backend.preflight_batch([jobs[3]])
        self.assertEqual(first_count, 2)
        self.assertEqual(len(self.tokenizations), first_count)
        self.assertEqual(self.backend.metrics['requests'], 0)

    def test_overlimit_input_is_rejected_without_truncation_or_model_call(self):
        document = '긴 상품 문서 ' * 1000
        job = replace(self.jobs[0], product={**self.jobs[0].product, 'document': document})
        def tokenize(request, **kwargs):
            self.assertTrue(request.full_url.endswith('/tokenize'))
            self.assertIn(document, json.loads(request.data)['content'])
            return io.BytesIO(json.dumps({'tokens': [1] * 7169}).encode())
        with patch('urllib.request.urlopen', side_effect=tokenize), self.assertRaisesRegex(ContractError, '8개 설문 묶음'):
            self.backend.preflight_batch([job])
        self.assertEqual(self.audits, [])
        self.assertEqual(self.backend.metrics['requests'], 0)

    def test_opt_in_versioning_and_ungrouped_v2_calls_remain_individual(self):
        self.assertTrue(self.backend.backend_id.endswith(':survey-choice-v2:survey-grouped-v1'))
        self.assertEqual(self.backend.batch_limit, 10)
        legacy = ClefBackend(revision='model-sha', runtime_revision='runtime-sha', survey_version=SURVEY_V2_SCENARIO_ID)
        self.assertTrue(legacy.backend_id.endswith(':survey-choice-v2'))
        self.assertEqual(legacy.batch_limit, 1)
        with patch('urllib.request.urlopen', side_effect=self.reply):
            outcomes = legacy.decide_batch(self.jobs)
        self.assert_decisions(outcomes)
        self.assertEqual(len(self.calls), 10)
        self.assertTrue(all(list(body['questions']) == ['decision'] for body in self.calls))
        for kwargs in ({'inference_protocol': 'unknown'}, {'inference_protocol': GROUPED_PROTOCOL},
                       {'inference_protocol': GROUPED_PROTOCOL, 'survey': True}):
            with self.assertRaises(ContractError):
                ClefBackend(**kwargs)


if __name__ == '__main__':
    unittest.main()
