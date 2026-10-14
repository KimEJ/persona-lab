"""Bounded rule and report checks; no inference runtime is used."""
import copy
import csv
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from persona_desktop.reporting import render_report
from persona_desktop.reporting import summary_facts
from persona_desktop.results import experiment_report
from persona_lab.acceptance import derive_acceptance
from persona_lab.contracts import Persona
from persona_lab.reports import export
from persona_lab.responses import SURVEY_V3_SCENARIO_ID
from persona_lab.runner import open_store
from persona_lab.survey import SURVEY_V3_QUESTIONS


def cell(choice, identifier='answer'):
    return {'job_id': identifier, 'choice': choice, 'status': 'backend_error' if choice == 'error' else choice}


class AcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.product = {'price': {'amount_minor': 100, 'currency': 'USD', 'billing': 'monthly'},
                        'valuation_unit': {'currency': 'USD', 'billing': 'monthly'},
                        'valuation_bands': [{'id': 'price_1', 'low_minor': 100, 'high_minor': 199},
                                            {'id': 'price_3', 'low_minor': 300, 'high_minor': None}]}

    def test_integer_interval_boundaries_and_usage_consideration(self):
        for amount, usage, band, expected in [(100, 'use', 'price_1', 'accept'),
                                              (100, 'consider', 'price_1', 'defer'),
                                              (101, 'use', 'price_1', 'uncertain'),
                                              (199, 'use', 'price_1', 'uncertain'),
                                              (200, 'use', 'price_1', 'reject'),
                                              (300, 'use', 'price_3', 'accept'),
                                              (301, 'use', 'price_3', 'uncertain')]:
            with self.subTest(amount=amount, usage=usage, band=band):
                self.product['price']['amount_minor'] = amount
                answer = derive_acceptance(self.product, cell(usage, 'usage-job'), cell(band, 'price-job'))
                self.assertEqual(answer['choice'], expected)
                self.assertEqual(answer['input_job_ids'], ['usage-job', 'price-job'])
                self.assertIsNone(answer['option_probabilities'])
                self.assertEqual(answer['probability_semantics'], 'not_provided')
        for key, value in [('currency', 'JPY'), ('billing', 'annual')]:
            product = copy.deepcopy(self.product)
            product['price'][key] = value
            self.assertEqual(derive_acceptance(product, cell('use'), cell('price_1'))['reason_code'], 'price_unit_mismatch')

    def test_missing_unknown_error_pending_and_free_precedence(self):
        for state in ('unknown', 'error', 'pending', 'not_run'):
            with self.subTest(state=state):
                self.assertEqual(derive_acceptance(self.product, cell(state), cell('price_1'))['choice'], state)
                self.assertEqual(derive_acceptance(self.product, cell('use'), cell(state))['choice'], state)
                free = {**self.product, 'price': {**self.product['price'], 'amount_minor': 0}}
                answer = derive_acceptance(free, cell('use', 'usage-job'), cell(state, 'price-job'))
                self.assertEqual((answer['choice'], answer['input_job_ids']), ('accept', ['usage-job']))
                self.assertEqual(derive_acceptance(free, cell('consider'), cell(state))['choice'], 'defer')
                self.assertEqual(derive_acceptance(free, cell('not_use'), cell(state))['choice'], 'reject')
        unset = {**self.product, 'price': None}
        self.assertEqual(derive_acceptance(unset, cell('not_use'), cell('unknown'))['choice'], 'reject')
        self.assertEqual(derive_acceptance(unset, cell('use'), cell('price_1'))['reason_code'], 'selling_price_missing')

    def test_report_exports_include_computed_outcome_without_model_count_inflation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'run.sqlite'
            source = {'source_id': 'test', 'version': 'v1', 'url': 'local:test',
                      'origin': 'synthetic', 'license_id': 'Test', 'license_url': 'local:license'}
            people = [Persona(f'p{i}', f'u{i}', source, {'age': 25, 'sex': 'male'}, '', {}, {}, {}) for i in range(2)]
            free = {**copy.deepcopy(self.product), 'id': 'free', 'name': '상품', 'document': '# 상품',
                    'intro': '상품', 'features': [], 'price_state': 'free'}
            free['price']['amount_minor'] = 0
            paid = copy.deepcopy(free)
            paid.update(id='paid', price_state='paid')
            paid['price']['amount_minor'] = 100
            spec = {'experiment_id': 'test', 'scenario': {'id': SURVEY_V3_SCENARIO_ID, 'events': []},
                    'questions': SURVEY_V3_QUESTIONS, 'products': [free, paid], 'repeats': 1,
                    'panel': {'selection': 'all'}, 'assumptions': {}}
            with open_store(path) as db:
                db.execute("INSERT INTO run VALUES (1,'fingerprint',36,36,'completed',?,?,'test','fixture',NULL)", (json.dumps(spec), json.dumps(source)))
                ordinal = 0
                for product in spec['products']:
                    for index, person in enumerate(people):
                        for question in spec['questions']:
                            domain = question['domain']
                            choice = ('use', 'consider')[index] if domain == 'usage' else 'price_1' if domain == 'fair_price' else question['choices'][0]
                            error = {'message': '평가 오류'} if product['id'] == 'free' and index == 0 and domain == 'fair_price' else None
                            record = {'job_id': f'{product["id"]}-{index}-{domain}', 'persona_id': person.persona_id,
                                      'uuid': person.uuid, 'product_id': product['id'], 'domain': domain, 'repeat': 0,
                                      'decision': None if error else {'choice': choice, 'status': 'ok'}, 'backend_error': error}
                            db.execute('INSERT INTO results VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                                       (ordinal, record['job_id'], person.persona_id, person.uuid, product['id'], question['id'], domain, 0,
                                        '' if error else choice, 'backend_error' if error else 'ok', json.dumps(record)))
                            ordinal += 1
            report = experiment_report(path, people, snapshot={'draft': {'title': '제품 설문'}, 'created_at': '2026-10-14T00:00:00Z'})
            response = report['responses']
            self.assertEqual((report['planned_jobs'], report['completed_jobs'], report['valid_decisions'], report['backend_errors']), (36, 36, 35, 1))
            self.assertEqual((len(spec['questions']), len(response['questions'])), (9, 10))
            self.assertEqual(response['usage_purchase'], [])
            self.assertFalse(any(question['domain'] == 'purchase' for question in response['questions']))
            self.assertEqual(response['people'][0]['items'][0]['fair_price']['choice'], 'error')
            self.assertEqual(response['people'][0]['items'][0]['acceptance']['choice'], 'accept')
            self.assertEqual(response['people'][1]['items'][1]['acceptance']['choice'], 'defer')
            self.assertEqual(response['price_points'][0]['domain'], 'acceptance')
            self.assertEqual([point['count'] for point in response['price_points'][0]['points']], [1, 1])
            for format in ('html', 'md'):
                body, _ = render_report(report, format)
                self.assertIn('최대 지불 의향 가격대', body)
                self.assertIn('가격 수용', body)
                self.assertNotIn('최종 선택', body)
                self.assertNotIn('적정가격', body)
            body, _ = render_report(report, 'csv')
            rows = list(csv.DictReader(io.StringIO(body)))
            acceptance = next(row for row in rows if row['product_id'] == 'free' and row['domain'] == 'acceptance' and row['choice'] == 'accept')
            self.assertEqual((acceptance['count'], acceptance['derived']), ('1', 'True'))
            self.assertEqual(json.loads(acceptance['input_job_ids_json']), ['free-0-usage'])
            self.assertIn('free_with_usage_intention', json.loads(acceptance['reason_counts_json']))
            body, _ = render_report(report, 'json')
            self.assertEqual(json.loads(body)['responses'], response)
            for format in ('json', 'csv', 'md'):
                body, _ = export(path, format)
                self.assertIn('acceptance' if format != 'md' else 'Price acceptance', body)
            with sqlite3.connect(path) as db:
                uncertain_spec = copy.deepcopy(spec)
                uncertain_spec['products'][1]['price']['amount_minor'] = 101
                db.execute('UPDATE run SET spec=?', (json.dumps(uncertain_spec),))
            uncertain_report = experiment_report(path, people)
            data = next(row for row in uncertain_report['responses']['statistics'] if row['product_id'] == 'paid' and row['domain'] == 'acceptance')
            self.assertEqual((data['counts']['uncertain'], data['excluded']['uncertain'], data['evaluated']), (2, 2, 0))
            # A wholly uncertain result must be shown as uncertainty, not as missing answers.
            uncertain_response = uncertain_report['responses']
            uncertain_response['products'] = list(reversed(uncertain_response['products']))
            self.assertIn('상한 구간 내 판정 불가 2명', summary_facts(uncertain_response)[2])
            with sqlite3.connect(path) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM results').fetchone()[0], 36)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM results WHERE domain='acceptance'").fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
