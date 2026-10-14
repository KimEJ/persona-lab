"""Finite fixtures check adaptive grids without loading a model."""

import copy
import unittest
from dataclasses import replace
from unittest.mock import patch

from persona_desktop.documents import valuation_fields, valuation_from_fields
from persona_desktop.valuation import (ALGORITHM_VERSION, LEGACY_ALGORITHM_VERSION, MAX_PILOTS, MAX_ROUNDS,
                                      LEGACY_WTP_ALGORITHM_VERSION, PREVIOUS_WTP_ALGORITHM_VERSION, WTP_ALGORITHM_VERSION,
                                      _conflicting_rounds, _decision_history, bands_from_boundaries, calibrate)
from persona_lab.contracts import ContractError, Decision, Persona, canonical, validate_valuation_bands
from persona_lab.finite_decision import ClefBackend
from persona_lab.responses import price_bands, SURVEY_V2_SCENARIO_ID, SURVEY_V3_SCENARIO_ID


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

    def test_opposite_extreme_rounds_stop_with_incompatible_pilot_evidence(self):
        for first, second, rest_first, rest_second in (
                ('price_0', 'price_3', 'price_1', 'price_2'),
                ('price_3', 'price_0', 'price_2', 'price_1')):
            with self.subTest(first=first):
                def choose(job, count):
                    round_index, pilot_index = divmod(count - 1, MAX_PILOTS)
                    if pilot_index < 10:
                        return first if round_index % 2 == 0 else second
                    return rest_first if round_index % 2 == 0 else rest_second

                backend = FiniteFixture(select=choose)
                resolved, state, complete = self.run_calibration(backend)
                entry = state['products']['item']
                self.assertTrue(complete)
                self.assertEqual(ALGORITHM_VERSION, state['algorithm_version'])
                self.assertEqual((entry['status'], resolved[0]['valuation_bands']), ('unavailable', []))
                self.assertEqual(len(backend.jobs), MAX_PILOTS * 2)
                self.assertEqual(len(entry['rounds']), 2)
                self.assertEqual(len(entry['rounds'][-1]['incompatible_uuids']), 10)
                self.assertIn('10명의 선택 가격대가 이전 응답과 겹치지 않습니다', entry['reason'])
                tuples = [tuple(band['low_minor'] for band in current['bands'][1:])
                          for current in entry['rounds']]
                self.assertEqual(len(tuples), len(set(tuples)))
                self.assertLessEqual(len(backend.jobs), MAX_PILOTS * MAX_ROUNDS)

    def test_legacy_partial_resume_preserves_job_identity_and_round_rules(self):
        def choose(job, count):
            return 'price_3' if job.product['valuation_bands'][1]['low_minor'] == 1 else 'price_0'

        legacy = FiniteFixture(select=choose)
        with patch('persona_desktop.valuation.ALGORITHM_VERSION', LEGACY_ALGORITHM_VERSION):
            _, partial, complete = self.run_calibration(legacy, cancelled=lambda: len(legacy.jobs) >= 5)
            baseline = FiniteFixture(select=choose)
            expected, expected_state, _ = self.run_calibration(baseline)
        self.assertFalse(complete)
        self.assertEqual(partial['algorithm_version'], LEGACY_ALGORITHM_VERSION)
        resumed = FiniteFixture(select=choose)
        actual, state, complete = self.run_calibration(resumed, state=copy.deepcopy(partial))
        self.assertTrue(complete)
        self.assertEqual([job.job_id for job in legacy.jobs + resumed.jobs],
                         [job.job_id for job in baseline.jobs])
        self.assertEqual(len(state['products']['item']['rounds']), 3)
        self.assertEqual(actual, expected)
        self.assertEqual(canonical(state), canonical(expected_state))
        untouched = FiniteFixture(select=choose)
        again, final_state, _ = self.run_calibration(untouched, state=copy.deepcopy(state))
        self.assertEqual(untouched.jobs, [])
        self.assertEqual(again, actual)
        self.assertEqual(canonical(final_state), canonical(state))
        self.assertEqual(again[0]['valuation_calibration']['algorithm_version'], LEGACY_ALGORITHM_VERSION)

    def test_refinement_outside_previous_interval_stays_unavailable(self):
        for outside in ('price_0', 'price_3'):
            with self.subTest(outside=outside):
                backend = FiniteFixture(select=lambda job, count:
                                        'price_1' if count <= MAX_PILOTS else outside)
                resolved, state, _ = self.run_calibration(backend)
                entry = state['products']['item']
                self.assertEqual((entry['status'], resolved[0]['valuation_bands']), ('unavailable', []))
                self.assertEqual(len(backend.jobs), MAX_PILOTS * 2)
                self.assertEqual(entry['rounds'][-1]['phase'], 'refinement')
                self.assertEqual(len(entry['rounds'][-1]['incompatible_uuids']), MAX_PILOTS)
                self.assertIn('세분화한 가격 범위를 벗어났으며', entry['reason'])

    def test_split_refinement_checks_people_without_a_dominant_conflict(self):
        for conflicting in (8, 1):
            with self.subTest(conflicting=conflicting):
                def choose(job, count):
                    if count <= MAX_PILOTS:
                        return 'price_1'
                    return 'price_0' if count - MAX_PILOTS <= conflicting else 'price_2'
                backend = FiniteFixture(select=choose)
                resolved, state, complete = self.run_calibration(backend, scenario_id=SURVEY_V3_SCENARIO_ID)
                entry = state['products']['item']
                self.assertTrue(complete)
                self.assertEqual(state['algorithm_version'], WTP_ALGORITHM_VERSION)
                self.assertEqual((entry['status'], resolved[0]['valuation_bands']), ('unavailable', []))
                self.assertEqual(len(backend.jobs), MAX_PILOTS * 2)
                self.assertEqual(len(entry['rounds'][-1]['incompatible_uuids']), conflicting)
                self.assertEqual(entry['rounds'][-1]['incompatible_with_round'], 0)
                self.assertIn(f'{conflicting}명의 선택 가격대가 이전 응답과 겹치지 않습니다', entry['reason'])

    def test_person_consistency_includes_nonadjacent_rounds_and_ignores_missing_answers(self):
        def round_state(boundaries, choice, extra=()):
            return {'bands': bands_from_boundaries(boundaries), 'outcomes': [
                {'uuid': 'same-person', 'kind': 'decision', 'decision': {'status': 'ok', 'choice': choice}}, *extra]}
        first = round_state([100, 1000, 10000], 'price_0', [
            {'uuid': 'unknown-person', 'kind': 'decision', 'decision': {'status': 'insufficient_information', 'choice': 'unknown'}},
            {'uuid': 'error-person', 'kind': 'error'}])
        middle = round_state([10000, 1000000, 100000000], 'price_0')
        last = round_state([100, 1000, 10000], 'price_1', [
            {'uuid': identifier, 'kind': 'decision', 'decision': {'status': 'ok', 'choice': 'price_1'}}
            for identifier in ('unknown-person', 'error-person')])
        self.assertEqual(_conflicting_rounds([middle], last), [])
        self.assertEqual(_conflicting_rounds([first, middle], last), [{'round': 0, 'uuids': ['same-person']}])
        shared_boundary = round_state([101, 1000, 10000], 'price_0')
        self.assertEqual(_conflicting_rounds([last], shared_boundary), [])

    def test_previous_wtp_resume_and_terminal_results_keep_their_recorded_policy(self):
        def choose(job, count):
            if job.product['valuation_bands'][2]['low_minor'] == 10000:
                return 'price_1'
            return 'price_0' if job.ordinal < 8 else 'price_2'
        original = FiniteFixture(select=choose)
        with patch('persona_desktop.valuation.WTP_ALGORITHM_VERSION', LEGACY_WTP_ALGORITHM_VERSION):
            _, partial, complete = self.run_calibration(original, scenario_id=SURVEY_V3_SCENARIO_ID,
                                                       cancelled=lambda: len(original.jobs) >= 5)
            baseline = FiniteFixture(select=choose)
            expected, expected_state, _ = self.run_calibration(baseline, scenario_id=SURVEY_V3_SCENARIO_ID)
        self.assertFalse(complete)
        self.assertEqual(partial['algorithm_version'], LEGACY_WTP_ALGORITHM_VERSION)
        resumed = FiniteFixture(select=choose)
        actual, state, _ = self.run_calibration(resumed, state=copy.deepcopy(partial), scenario_id=SURVEY_V3_SCENARIO_ID)
        self.assertEqual([job.job_id for job in original.jobs + resumed.jobs], [job.job_id for job in baseline.jobs])
        self.assertEqual(canonical(state), canonical(expected_state))
        self.assertEqual(actual, expected)
        untouched = FiniteFixture()
        result, frozen, _ = self.run_calibration(untouched, state=copy.deepcopy(state), scenario_id=SURVEY_V3_SCENARIO_ID)
        self.assertEqual(untouched.jobs, [])
        self.assertEqual((result, canonical(frozen)), (actual, canonical(state)))

    def test_history_refines_same_person_and_resume_keeps_exact_requests(self):
        original = FiniteFixture()
        _, partial, complete = self.run_calibration(original, scenario_id=SURVEY_V3_SCENARIO_ID,
                                                   cancelled=lambda: len(original.jobs) >= MAX_PILOTS + 3)
        self.assertFalse(complete)
        self.assertEqual(partial['algorithm_version'], 'auto-wtp-v3')
        self.assertEqual(partial['history_protocol'], 'price-calibration-history-v1')
        resumed = FiniteFixture()
        actual, final, _ = self.run_calibration(resumed, state=copy.deepcopy(partial), scenario_id=SURVEY_V3_SCENARIO_ID)
        baseline = FiniteFixture()
        expected, frozen, _ = self.run_calibration(baseline, scenario_id=SURVEY_V3_SCENARIO_ID)
        self.assertEqual(actual, expected)
        self.assertEqual(canonical(final), canonical(frozen))
        self.assertEqual([job.job_id for job in original.jobs + resumed.jobs], [job.job_id for job in baseline.jobs])
        self.assertEqual([job.calibration_history for job in original.jobs + resumed.jobs],
                         [job.calibration_history for job in baseline.jobs])
        self.assertTrue(all(job.calibration_history is None for job in baseline.jobs[:MAX_PILOTS]))
        for job in baseline.jobs[MAX_PILOTS:]:
            prior = next(value for value in baseline.jobs[:MAX_PILOTS] if value.persona.uuid == job.persona.uuid)
            self.assertEqual(job.calibration_history['persona_id'], job.persona.persona_id)
            self.assertEqual(job.calibration_history['records'], [{
                'round': 0, 'phase': 'broad', 'job_id': prior.job_id, 'status': 'ok',
                'interval': {'low_minor': 100, 'high_minor': 9999}}])
        # A different recorded judgment must produce a different next request ID.
        changed = copy.deepcopy(partial)
        before = changed['products']['item']['rounds'][0]['outcomes']
        waiting_uuid = changed['products']['item']['pilot_uuids'][3]
        next(value for value in before if value['uuid'] == waiting_uuid)['decision']['choice'] = 'price_2'
        altered = FiniteFixture()
        self.run_calibration(altered, state=changed, scenario_id=SURVEY_V3_SCENARIO_ID,
                             cancelled=lambda: len(altered.jobs) == 1)
        self.assertNotEqual(altered.jobs[0].job_id, resumed.jobs[0].job_id)

    def test_history_unknown_and_error_do_not_become_price_constraints(self):
        persona = people(1)[0]
        entry = {'unit': {'currency': 'JPY', 'billing': 'one_time'}, 'rounds': [
            {'phase': 'broad', 'bands': bands_from_boundaries([100, 10000, 1000000]), 'outcomes': [
                {'uuid': persona.uuid, 'job_id': 'unknown-source', 'kind': 'decision',
                 'decision': {'status': 'insufficient_information', 'choice': 'unknown'}},
                {'uuid': 'another-person', 'job_id': 'other', 'kind': 'decision',
                 'decision': {'status': 'ok', 'choice': 'price_3'}}]},
            {'phase': 'contract', 'bands': bands_from_boundaries([1, 100, 10000]), 'outcomes': [
                {'uuid': persona.uuid, 'job_id': 'error-source', 'kind': 'error',
                 'error': {'message': 'do not pass diagnostic text to model'}}]}]}
        history = _decision_history(entry, persona, 2)
        self.assertEqual(history['records'], [
            {'round': 0, 'phase': 'broad', 'job_id': 'unknown-source', 'status': 'unknown'},
            {'round': 1, 'phase': 'contract', 'job_id': 'error-source', 'status': 'error'}])
        self.assertEqual(_decision_history(entry, persona, 0), None)

    def test_guard_only_wtp_resume_preserves_no_history_and_strict_policy(self):
        def choose(job, count):
            return 'price_1' if job.product['valuation_bands'][2]['low_minor'] == 10000 else (
                'price_0' if job.ordinal < 8 else 'price_2')
        original = FiniteFixture(select=choose)
        with patch('persona_desktop.valuation.WTP_ALGORITHM_VERSION', PREVIOUS_WTP_ALGORITHM_VERSION):
            _, partial, _ = self.run_calibration(original, scenario_id=SURVEY_V3_SCENARIO_ID,
                                                cancelled=lambda: len(original.jobs) >= MAX_PILOTS + 3)
            baseline = FiniteFixture(select=choose)
            expected, frozen, _ = self.run_calibration(baseline, scenario_id=SURVEY_V3_SCENARIO_ID)
        resumed = FiniteFixture(select=choose)
        actual, final, _ = self.run_calibration(resumed, state=copy.deepcopy(partial), scenario_id=SURVEY_V3_SCENARIO_ID)
        self.assertEqual([job.job_id for job in original.jobs + resumed.jobs], [job.job_id for job in baseline.jobs])
        self.assertTrue(all(job.calibration_history is None for job in original.jobs + resumed.jobs))
        self.assertNotIn('history_protocol', final)
        self.assertEqual((actual, canonical(final)), (expected, canonical(frozen)))
        self.assertEqual(final['products']['item']['status'], 'unavailable')

    def test_disjoint_dominant_finite_band_cannot_refine_into_ready(self):
        for first, second in (('price_3', 'price_1'), ('price_0', 'price_2')):
            with self.subTest(first=first):
                backend = FiniteFixture(select=lambda job, count:
                                        first if count <= MAX_PILOTS else second)
                resolved, state, _ = self.run_calibration(backend)
                entry = state['products']['item']
                self.assertEqual((entry['status'], resolved[0]['valuation_bands']), ('unavailable', []))
                self.assertEqual(len(backend.jobs), MAX_PILOTS * 2)
                self.assertEqual(len(entry['rounds'][-1]['incompatible_uuids']), MAX_PILOTS)
                self.assertEqual(entry['rounds'][-1]['incompatible_with_round'], 0)
                self.assertIn('가격 범위를 조정한 뒤', entry['reason'])

    def test_repeated_candidate_with_disjoint_valid_pilots_stops_without_duplicate_requests(self):
        for first, second in (('price_0', 'price_3'), ('price_3', 'price_0')):
            with self.subTest(first=first):
                def choose(job, count):
                    round_index, pilot_index = divmod(count - 1, MAX_PILOTS)
                    if round_index % 2 == 0:
                        return first if pilot_index < 6 else 'unknown'
                    return second if pilot_index >= 6 else 'unknown'

                backend = FiniteFixture(select=choose)
                resolved, state, _ = self.run_calibration(backend)
                entry = state['products']['item']
                self.assertEqual((entry['status'], resolved[0]['valuation_bands']), ('unavailable', []))
                self.assertIn('이미 평가한 가격 범위로 돌아가므로', entry['reason'])
                tuples = [tuple(band['low_minor'] for band in current['bands'][1:])
                          for current in entry['rounds']]
                self.assertEqual(len(tuples), len(set(tuples)))
                self.assertEqual(len(backend.jobs), MAX_PILOTS * 2)
                self.assertLessEqual(len(backend.jobs), MAX_PILOTS * MAX_ROUNDS)

    def test_unknown_algorithm_version_is_not_reinterpreted(self):
        backend = FiniteFixture()
        _, state, _ = self.run_calibration(backend)
        state['algorithm_version'] = 'auto-price-unrecognized'
        with self.assertRaisesRegex(ContractError, '알고리즘 버전'):
            self.run_calibration(FiniteFixture(), state=state)

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
