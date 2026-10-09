"""Finite fixtures check adaptive grids without loading a model."""

import copy
import unittest
from dataclasses import replace

from persona_desktop.documents import valuation_fields, valuation_from_fields
from persona_desktop.valuation import MAX_PILOTS, MAX_ROUNDS, calibrate
from persona_lab.contracts import ContractError, Decision, Persona, canonical, validate_valuation_bands
from persona_lab.finite_decision import ClefBackend
from persona_lab.responses import price_bands, SURVEY_V2_SCENARIO_ID


def people(count=30):
    return [Persona(f'person-{index}', f'uuid-{index}', {'source_id': 'fixture', 'version': '1'},
                    {'uuid': f'uuid-{index}', 'age': 30 + index, 'persona': '毎日設計資料を整理している。'},
                    f'content-{index}', {}, {}, {}) for index in range(count)]


def product(identifier='item', amount=1000, currency='JPY', billing='one_time'):
    return {'id': identifier, 'name': '설계 도구', 'intro': '매일 자료를 찾는 설계 업무용 도구.',
            'document': '설계 자료 검색과 정리에 사용합니다.\n가격: 1,000 JPY 일시불', 'features': [],
            'price': {'amount_minor': amount, 'currency': currency, 'billing': billing},
            'valuation_unit': {'currency': currency, 'billing': billing}, 'valuation_bands': [], 'valuation_mode': 'auto'}


def decision(job, choice):
    return Decision(choice, 'insufficient_information' if choice == 'unknown' else 'ok',
                    ('fixture_finite_choice',), ('product.document',), evidence_semantics='supplied_input_only',
                    missing_information=('활용 빈도',) if choice == 'unknown' else (),
                    option_probabilities={value: float(value == choice) for value in job.question['choices'] if value != 'not_run'},
                    probability_semantics='model_option_distribution')


class FiniteFixture:
    backend_id = 'fixture-auto-price-v1'

    def __init__(self, amount=2500, select=None):
        self.amount, self.select, self.jobs = amount, select, []

    def decide(self, job):
        self.jobs.append(job)
        choice = self.select(job, len(self.jobs)) if self.select else next(
            band['id'] for band in job.product['valuation_bands']
            if self.amount >= band['low_minor'] and (band['high_minor'] is None or self.amount <= band['high_minor']))
        if isinstance(choice, Exception):
            raise choice
        return decision(job, choice)


class AutoValuationTests(unittest.TestCase):
    panel = {'selection': 'random', 'sample_size': 10, 'sample_seed': 17,
             'sampling_version': 'hash-rank-v1', 'selected_uuids': [f'uuid-{index}' for index in range(10)]}

    def run_calibration(self, backend, products=None, population=None, **kwargs):
        return calibrate(products or [product()], people() if population is None else population,
                         self.panel, backend, 'experiment', 7, **kwargs)

    def test_new_default_auto_and_legacy_manual_remain_distinct(self):
        fresh = valuation_fields()
        self.assertEqual(fresh, {'mode': 'auto', 'currency': 'JPY', 'billing': 'one_time', 'boundaries': ['', '', '']})
        self.assertEqual(valuation_from_fields(fresh), ({'currency': 'JPY', 'billing': 'one_time'}, []))
        self.assertEqual(valuation_fields({'valuation_bands': []})['mode'], 'manual')
        existing = valuation_fields({'valuation_unit': {'currency': 'JPY', 'billing': 'one_time'},
                                     'valuation_bands': price_bands('JPY')})
        self.assertEqual(existing['mode'], 'manual')
        self.assertEqual(valuation_from_fields(existing)[1], price_bands('JPY'))
        legacy = {key: value for key, value in fresh.items() if key != 'mode'}
        self.assertEqual(valuation_from_fields(legacy)[1], [])
        for bad in ('automatic', None, 1):
            with self.assertRaises(ContractError):
                valuation_from_fields({**fresh, 'mode': bad})
        with self.assertRaises(ContractError):
            valuation_from_fields({**fresh, 'currency': 'XXX'})
        with self.assertRaises(ContractError):
            valuation_from_fields({**fresh, 'mode': 'manual', 'boundaries': ['100', '', '1000']})

    def test_high_and_low_cost_scales_use_continuous_bounded_grids(self):
        for amount in (20, 15000000):
            with self.subTest(amount=amount):
                backend = FiniteFixture(amount)
                resolved, state, complete = self.run_calibration(backend)
                self.assertTrue(complete)
                entry = state['products']['item']
                self.assertEqual(entry['status'], 'resolved')
                self.assertEqual(resolved[0]['valuation_calibration']['status'], 'ready')
                self.assertLessEqual(len(backend.jobs), MAX_PILOTS * MAX_ROUNDS)
                self.assertGreater(len(entry['rounds']), 1)
                self.assertEqual(state['completed'], state['total'])
                for round_state in entry['rounds']:
                    validate_valuation_bands(round_state['bands'])
                    self.assertEqual(round_state['cursor'], MAX_PILOTS)
                if amount > 1000000:
                    self.assertGreater(resolved[0]['valuation_bands'][2]['low_minor'], 1000000)
                else:
                    self.assertLess(resolved[0]['valuation_bands'][1]['low_minor'], 100)

    def test_unknown_and_errors_do_not_create_amounts_and_raw_trace_survives(self):
        backend = FiniteFixture(select=lambda job, count: OSError('fixture outage') if count % 3 == 0 else 'unknown')
        resolved, state, complete = self.run_calibration(backend)
        entry = state['products']['item']
        self.assertTrue(complete)
        self.assertEqual((entry['status'], resolved[0]['valuation_bands']), ('unavailable', []))
        self.assertIn('판단 불가 8명, 오류 4명', entry['reason'])
        outcomes = entry['rounds'][0]['outcomes']
        self.assertEqual(outcomes[0]['decision']['missing_information'], ('활용 빈도',))
        self.assertEqual(outcomes[2]['error']['type'], 'OSError')
        self.assertEqual(entry['valid_count'], 0)
        canonical(state)

    def test_validation_failure_keeps_raw_decision_and_is_not_unknown(self):
        backend = FiniteFixture()
        backend.decide = lambda job: replace(decision(job, 'price_1'), valuation={'amount_minor': 500, 'currency': 'JPY', 'billing': 'one_time'})
        resolved, state, _ = self.run_calibration(backend)
        outcome = state['products']['item']['rounds'][0]['outcomes'][0]
        self.assertEqual(outcome['kind'], 'error')
        self.assertEqual(outcome['raw_decision']['valuation']['amount_minor'], 500)
        self.assertEqual(resolved[0]['valuation_calibration']['valid_count'], 0)

    def test_resume_reuses_recorded_pilots_outcomes_and_terminal_grid(self):
        backend = FiniteFixture()
        checkpoints = []
        result, state, complete = self.run_calibration(backend, cancelled=lambda: len(backend.jobs) >= 5,
                                                     checkpoint=lambda state: checkpoints.append(copy.deepcopy(state)))
        self.assertFalse(complete)
        self.assertEqual(state['products']['item']['rounds'][0]['cursor'], 5)
        first_ids = [job.job_id for job in backend.jobs]
        resumed = FiniteFixture()
        result, final_state, complete = self.run_calibration(resumed, state=copy.deepcopy(state),
                                                           checkpoint=lambda state: checkpoints.append(copy.deepcopy(state)))
        self.assertTrue(complete)
        self.assertTrue(set(first_ids).isdisjoint(job.job_id for job in resumed.jobs))
        untouched = FiniteFixture()
        result_again, state_again, complete = self.run_calibration(untouched, state=copy.deepcopy(final_state))
        self.assertTrue(complete)
        self.assertEqual(untouched.jobs, [])
        self.assertEqual(result, result_again)
        completed = [value['completed'] for value in checkpoints]
        self.assertEqual(completed, sorted(completed))
        self.assertTrue(all(snapshot['completed'] == sum(round_state['cursor'] for entry in snapshot['products'].values()
                            for round_state in entry['rounds']) for snapshot in checkpoints))
        self.assertEqual(state_again['products']['item']['pilot_uuids'], state['products']['item']['pilot_uuids'])

    def test_offer_price_cannot_change_inputs_grid_or_shared_offer_comparison(self):
        first = product(amount=1000)
        second = product('item-two', amount=900000)
        second['document'] = second['document'].replace('1,000', '900,000')
        backend = FiniteFixture()
        resolved, state, _ = self.run_calibration(backend, products=[first, second])
        self.assertEqual(resolved[0]['valuation_bands'], resolved[1]['valuation_bands'])
        self.assertEqual(state['products']['item-two']['reused_from'], 'item')
        self.assertEqual(state['products']['item-two']['rounds'], [])
        self.assertEqual(len(backend.jobs), MAX_PILOTS * 2)
        clef = ClefBackend(survey_version=SURVEY_V2_SCENARIO_ID)
        for job in backend.jobs:
            self.assertIsNone(job.product['price'])
            self.assertNotIn('가격:', job.product['document'])
            original = clef.request_body(job)
            changed = {**job.product, 'price': second['price'], 'document': job.product['document'] + '\n가격: 900,000 JPY 일시불'}
            self.assertEqual(original, clef.request_body(replace(job, product=changed)))
        separate = FiniteFixture()
        result_two, state_two, _ = self.run_calibration(separate, products=[{**second, 'id': 'item'}])
        self.assertEqual(resolved[0]['valuation_bands'], result_two[0]['valuation_bands'])
        self.assertEqual(state['products']['item']['pilot_uuids'], state_two['products']['item']['pilot_uuids'])
        self.assertEqual([job.product['valuation_bands'] for job in backend.jobs],
                         [job.product['valuation_bands'] for job in separate.jobs])

    def test_pilot_filter_disjointness_and_overlap_fallback_are_recorded(self):
        backend = FiniteFixture()
        _, state, _ = self.run_calibration(backend)
        entry = state['products']['item']
        self.assertEqual(len(entry['pilot_uuids']), MAX_PILOTS)
        self.assertEqual(entry['overlap_uuids'], [])
        population = people(14)
        _, state, _ = self.run_calibration(FiniteFixture(), population=population)
        self.assertEqual(len(state['products']['item']['overlap_uuids']), 8)
        filtered = {**self.panel, 'age_min': 55, 'selected_uuids': [f'uuid-{index}' for index in range(25, 30)]}
        _, state, _ = calibrate([product()], people(), filtered, FiniteFixture(), 'experiment', 7)
        self.assertTrue(all(int(identifier.split('-')[-1]) >= 25 for identifier in state['products']['item']['pilot_uuids']))

    def test_saturated_scale_exhaustion_is_unavailable_and_request_bound_holds(self):
        backend = FiniteFixture(amount=10**15)
        resolved, state, complete = self.run_calibration(backend)
        self.assertTrue(complete)
        self.assertEqual(resolved[0]['valuation_bands'], [])
        self.assertEqual(len(backend.jobs), MAX_PILOTS * 3)
        self.assertIn('범위를 확정하지 못했습니다', state['products']['item']['reason'])

    def test_sparse_valid_answers_stay_sparse_and_manual_config_never_runs(self):
        def choose(job, count):
            return 'price_1' if count <= 3 else 'unknown'
        resolved, state, _ = self.run_calibration(FiniteFixture(select=choose))
        self.assertEqual(resolved[0]['valuation_bands'], [])
        self.assertEqual(state['products']['item']['valid_count'], 3)
        manual = {**product(), 'valuation_mode': 'manual', 'valuation_bands': price_bands('JPY')}
        backend = FiniteFixture()
        resolved, state, complete = self.run_calibration(backend, products=[manual])
        self.assertTrue(complete)
        self.assertEqual(resolved[0], manual)
        self.assertEqual(backend.jobs, [])

    def test_multi_modal_answers_keep_the_broad_grid_without_equalizing_counts(self):
        backend = FiniteFixture(select=lambda job, count: 'price_1' if count % 3 else 'price_2')
        resolved, state, _ = self.run_calibration(backend)
        self.assertEqual(len(backend.jobs), MAX_PILOTS)
        self.assertEqual(state['products']['item']['rounds'][0]['choice_counts'], {'price_1': 8, 'price_2': 4})
        self.assertEqual(resolved[0]['valuation_bands'], state['products']['item']['rounds'][0]['bands'])

    def test_resume_in_new_round_keeps_candidate_and_rejects_changed_identity(self):
        backend = FiniteFixture(amount=15000000)
        _, state, complete = self.run_calibration(backend, cancelled=lambda: len(backend.jobs) >= MAX_PILOTS + 3)
        self.assertFalse(complete)
        original = copy.deepcopy(state)
        self.assertEqual(len(state['products']['item']['rounds']), 2)
        self.assertEqual(state['products']['item']['rounds'][1]['cursor'], 3)
        resumed = FiniteFixture(amount=15000000)
        _, final_state, _ = self.run_calibration(resumed, state=state)
        self.assertEqual(resumed.jobs[0].product['valuation_bands'], original['products']['item']['rounds'][1]['bands'])
        self.assertEqual(final_state['products']['item']['status'], 'resolved')
        altered = people()
        altered[0] = replace(altered[0], source={**altered[0].source, 'version': '2'})
        with self.assertRaises(ContractError):
            self.run_calibration(FiniteFixture(), state=original, population=altered)
        changed = FiniteFixture()
        changed.backend_id = 'changed-fixture-version'
        with self.assertRaises(ContractError):
            self.run_calibration(changed, state=original)
        with self.assertRaises(ContractError):
            calibrate([product()], people(), {**self.panel, 'sample_seed': 99}, FiniteFixture(),
                      'experiment', 7, state=original)

    def test_shared_terminal_state_never_repeats_exploration_and_units_are_respected(self):
        backend = FiniteFixture()
        products = [product(), product('same-offer', amount=900000)]
        original, state, _ = self.run_calibration(backend, products=products)
        resumed = FiniteFixture()
        resolved, _, _ = self.run_calibration(resumed, products=products, state=copy.deepcopy(state))
        self.assertEqual(resolved, original)
        self.assertEqual(resumed.jobs, [])
        for currency in ('JPY', 'KRW', 'USD', 'EUR'):
            for billing in ('one_time', 'monthly', 'annual'):
                with self.subTest(currency=currency, billing=billing):
                    backend = FiniteFixture(select=lambda job, count: 'price_1' if count % 3 else 'price_2')
                    resolved, _, _ = self.run_calibration(backend, products=[product(currency=currency, billing=billing)])
                    self.assertEqual(resolved[0]['valuation_unit'], {'currency': currency, 'billing': billing})
                    validate_valuation_bands(resolved[0]['valuation_bands'])
                    self.assertTrue(all(job.product['valuation_unit'] == resolved[0]['valuation_unit'] for job in backend.jobs))


if __name__ == '__main__':
    unittest.main()
