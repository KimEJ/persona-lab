"""Regression checks for feasibility metrics; actual inference stays in the tool."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from check_decision_model import compare_rows, control_job, probabilities, summarize


class DecisionControlTests(unittest.TestCase):
    def row(self, choice='use', group='repeat'):
        return {
            'case': 'case', 'group': group, 'request_sha256': 'same', 'error': None,
            'decision': {'choice': choice, 'option_probabilities': {'use': .7, 'not_use': .2, 'unknown': .1}},
            'expected': [choice], 'baseline_choice': choice,
        }

    def test_repeat_comparison_checks_request_choice_and_full_distribution(self):
        reference = self.row()
        self.assertTrue(compare_rows([reference, copy.deepcopy(reference)])['passed'])
        changed = copy.deepcopy(reference)
        changed['decision']['option_probabilities']['use'] -= 1e-7
        changed['decision']['option_probabilities']['not_use'] += 1e-7
        result = compare_rows([changed], reference)
        self.assertTrue(result['passed'])
        self.assertFalse(result['probabilities_exact'])
        changed['decision']['option_probabilities']['use'] -= .01
        self.assertFalse(compare_rows([changed], reference)['passed'])
        changed = copy.deepcopy(reference)
        changed['request_sha256'] = 'different'
        self.assertFalse(compare_rows([changed], reference)['passed'])
        self.assertFalse(compare_rows([self.row('unknown')], reference)['passed'])

    def test_failed_baseline_and_partial_repeats_never_pass(self):
        failed = self.row()
        failed.update(decision=None, error={'type': 'ContractError'})
        self.assertFalse(compare_rows([self.row()], failed)['passed'])
        self.assertFalse(compare_rows([self.row(), failed])['passed'])
        self.assertFalse(compare_rows([])['passed'])

    def test_engineering_behavior_and_order_failures_are_separate(self):
        repeat, seed = [self.row()], [self.row(group='seed')]
        behavioral = self.row('unknown', 'behavior')
        order = self.row(group='order')
        metrics, ready = summarize([behavioral, *repeat, *seed, order], repeat, seed, [order])
        self.assertTrue(ready)
        self.assertTrue(metrics['condition_adherence']['passed'])
        behavioral['expected'] = ['use']
        order['baseline_choice'] = 'not_use'
        metrics, ready = summarize([behavioral, *repeat, *seed, order], repeat, seed, [order])
        self.assertFalse(ready)
        self.assertTrue(metrics['engineering']['passed'])
        self.assertEqual(metrics['condition_adherence']['failures'], ['case'])
        self.assertEqual(metrics['option_order']['changed_choices'], ['case'])

    def test_probabilities_reject_missing_nonfinite_and_unnormalized_values(self):
        decision = self.row()['decision']
        self.assertEqual(probabilities(decision, ['use', 'not_use', 'unknown']), decision['option_probabilities'])
        for invalid in ({'use': 1}, {'use': float('nan'), 'not_use': 0, 'unknown': 0}, {'use': .4, 'not_use': .4, 'unknown': .4}):
            with self.assertRaises(ValueError):
                probabilities({'option_probabilities': invalid}, ['use', 'not_use', 'unknown'])

    def test_control_inputs_have_fixed_metadata_and_explicit_preferences(self):
        usage = control_job('need', 'usage')
        self.assertEqual(usage, control_job('need', 'usage'))
        self.assertIn('2,000,000 JPY', usage.persona.raw['persona'])
        usd = control_job('USD', 'fair_price', currency='USD')
        self.assertIn('9.99 USD', usd.persona.raw['persona'])
        self.assertEqual(usd.product['valuation_bands'][0]['high_minor'], 999)
        self.assertEqual(control_job('missing_context', 'usage').persona.raw, {'uuid': 'decision-control-missing_context', 'age': 35, 'sex': '女'})


if __name__ == '__main__':
    unittest.main()
