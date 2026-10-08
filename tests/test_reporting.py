"""Report counts, archival catalogs and safe standalone export share one snapshot."""
import copy
import csv
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from persona_desktop.reporting import render_report
from persona_desktop.results import experiment_report, response_report
from persona_lab.contracts import Persona
from persona_lab.responses import SURVEY_SCENARIO_ID, SURVEY_V2_SCENARIO_ID, price_bands
from persona_lab.runner import open_store
from persona_lab.survey import SURVEY_QUESTIONS, SURVEY_V2_QUESTIONS


class ReportingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'run.sqlite'
        self.source = {'source_id': 'authored-fixture', 'version': 'v1', 'url': 'local:test',
                       'license_id': 'LicenseRef-Test', 'license_url': 'local:license', 'record_count': 4}
        self.people = [Persona(f'p{i}', f'u{i}', self.source, {'age': 25 + i * 15, 'sex': '女性' if i % 2 else '男性'}, '', {}, {}, {}) for i in range(4)]
        product = {'id': 'a', 'name': '=메모 <script>alert(1)</script>', 'document': '# 도구\n검색 <img src=x onerror=alert(1)>',
                   'intro': '검색', 'features': [], 'price': {'amount_minor': 0, 'currency': 'JPY', 'billing': 'one_time'},
                   'price_state': 'free', 'valuation_unit': {'currency': 'JPY', 'billing': 'one_time'}, 'valuation_bands': price_bands('JPY')}
        other = copy.deepcopy(product)
        other.update(id='b', price={'amount_minor': 2000, 'currency': 'JPY', 'billing': 'one_time'}, price_state='paid')
        self.spec = {'experiment_id': 'report-test', 'scenario': {'id': SURVEY_V2_SCENARIO_ID, 'events': []},
                     'questions': SURVEY_V2_QUESTIONS, 'products': [product, other], 'repeats': 2,
                     'panel': {'selection': 'all'}, 'assumptions': {}}
        self.snapshot = {'draft': {'title': '<script>title</script>'}, 'created_at': '2026-10-07T03:00:00Z',
                         'spec': self.spec, 'source': self.source}
        with open_store(self.path) as db:
            db.execute("INSERT INTO run VALUES (1,'fingerprint',0,160,'paused',?,?, 'clef-test','fixture',NULL)", (json.dumps(self.spec), json.dumps(self.source)))
        self.add(0, 'a', 'usage', 'use')
        self.add(0, 'a', 'purchase', 'decline')
        self.add(1, 'a', 'usage', 'unknown')
        self.add(1, 'a', 'purchase', 'unknown')
        self.add(2, 'a', 'usage', 'error')
        self.add(0, 'a', 'benefit', 'not_applicable')
        self.add(0, 'a', 'fair_price', 'price_1')
        self.add(0, 'b', 'usage', 'consider')
        self.add(0, 'b', 'purchase', 'buy')
        self.add(1, 'b', 'purchase', 'error')
        for person in range(4):
            self.add(person, 'a', 'usage', 'use', repeat=1)
            self.add(person, 'a', 'purchase', 'buy', repeat=1)

    def add(self, index, product, domain, choice, repeat=0):
        question = next(question for question in self.spec['questions'] if question['domain'] == domain)
        person = self.people[index]
        error = {'message': '실행 <오류>'} if choice == 'error' else None
        record = {'job_id': f'{repeat}-{product}-{domain}-{index}', 'persona_id': person.persona_id, 'uuid': person.uuid,
                  'product_id': product, 'domain': domain, 'repeat': repeat,
                  'decision': None if error else {'choice': choice, 'status': 'insufficient_information' if choice == 'unknown' else 'ok',
                                                 'reason': '', 'missing_information': ['현재 방식'] if choice == 'unknown' else []}, 'backend_error': error}
        with sqlite3.connect(self.path) as db:
            ordinal = db.execute('SELECT COUNT(*) FROM results').fetchone()[0]
            db.execute('INSERT INTO results VALUES (?,?,?,?,?,?,?,?,?,?,?)', (ordinal, record['job_id'], person.persona_id, person.uuid, product, question['id'], domain, repeat, choice, 'backend_error' if error else record['decision']['status'], json.dumps(record)))
            db.execute('UPDATE run SET cursor=?', (ordinal + 1,))

    def report(self, repeat=0):
        return experiment_report(self.path, self.people, repeat, snapshot=self.snapshot, include_calls=True)

    def test_one_read_snapshot_preserves_people_repeat_and_response_states(self):
        connect = sqlite3.connect
        with patch('sqlite3.connect', wraps=connect) as opened:
            report = self.report()
        self.assertEqual(opened.call_count, 1)
        response = report['responses']
        self.assertEqual((response['count'], len(response['questions'])), (4, 10))
        usage = next(data for data in response['statistics'] if data['product_id'] == 'a' and data['domain'] == 'usage')
        self.assertEqual({key: usage['counts'][key] for key in ('use', 'unknown', 'error', 'pending')}, {'use': 1, 'unknown': 1, 'error': 1, 'pending': 1})
        self.assertEqual((sum(usage['counts'].values()), usage['denominator'], usage['shares']['use']), (4, 4, .25))
        self.assertEqual(next(item for item in response['statistics'] if item['product_id'] == 'a' and item['domain'] == 'benefit')['counts']['not_applicable'], 1)
        self.assertEqual(response['usage_purchase'][0]['paired_count'], 2)
        self.assertEqual(response['usage_purchase'][0]['excluded_count'], 2)
        self.assertEqual(response['price_points'][0]['points'][0]['count'], 0)
        self.assertEqual(response['price_points'][0]['points'][1]['count'], 1)
        comparison = next(pair for pair in response['paired_comparisons'] if pair['domain'] == 'purchase')
        self.assertEqual((comparison['paired_count'], comparison['excluded_count']), (1, 3))
        self.assertEqual(report['model_calls'], [])
        second = self.report(1)['responses']
        self.assertEqual(next(data for data in second['statistics'] if data['product_id'] == 'a' and data['domain'] == 'purchase')['counts']['buy'], 4)
        self.assertEqual(response['context']['model']['name'], 'clef-test')
        self.assertIn('<img', response['products'][0]['document'])

    def test_standalone_html_and_csv_escape_input_and_match_authoritative_counts(self):
        report = self.report()
        html, mime = render_report(report, 'html')
        self.assertEqual(mime, 'text/html; charset=utf-8')
        self.assertNotIn('<script>', html)
        self.assertNotIn('<img ', html)
        self.assertIn('&lt;script&gt;', html)
        self.assertIn('@page { size: A4;', html)
        self.assertIn('font-size: 10.5pt', html)
        self.assertIn('Content-Security-Policy', html)
        self.assertIn('default-src &apos;none&apos;', html)
        self.assertIn('<svg', html)
        self.assertIn('해당 없음', html)
        self.assertNotIn('<script src=', html)
        self.assertNotIn('<link ', html)
        self.assertIn('확인할 사례', html)
        self.assertNotIn('eyebrow', html)
        self.assertEqual(html.count('<pre>'), 1)
        self.assertIn('1 · =메모', html)
        self.assertIn('2 · =메모', html)
        self.assertIn('<table class="joint">', html)
        self.assertIn('<table class="methods">', html)
        header = html.split('<p class="meta">', 1)[1].split('</p>', 1)[0]
        self.assertIn('2026년 10월 7일 12:00', header)
        self.assertIn('중단', header)
        self.assertNotIn('paused', header)
        self.assertNotIn('<section class="page"><h2>같은 인물의 선택 비교', html)
        csv_body, _ = render_report(report, 'csv')
        rows = list(csv.DictReader(io.StringIO(csv_body)))
        row = next(row for row in rows if row['product_id'] == 'a' and row['domain'] == 'usage' and row['choice'] == 'use')
        self.assertEqual((row['count'], row['selected_people_denominator'], row['share'], row['repeat']), ('1', '4', '0.25', '0'))
        self.assertTrue(row['product_name'].startswith("'="))
        markdown, _ = render_report(report, 'md')
        self.assertNotIn('<script>', markdown)
        self.assertIn('1 | 4 | 25.0%', markdown)
        exported, _ = render_report(report, 'json')
        self.assertEqual(json.loads(exported)['responses']['statistics'], report['responses']['statistics'])

    def test_missing_price_grid_and_old_catalog_are_not_reinterpreted(self):
        spec = copy.deepcopy(self.spec)
        spec['products'][1].update(price=None, valuation_bands=[])
        with sqlite3.connect(self.path) as db:
            db.execute('DELETE FROM results WHERE product_id=?', ('b',))
            db.execute('UPDATE run SET spec=?', (json.dumps(spec),))
        response = self.report()['responses']
        self.assertTrue(all(person['items'][1]['fair_price']['choice'] == 'not_run' and person['items'][1]['purchase']['choice'] == 'not_run' for person in response['people']))
        self.assertEqual(response['price_points'], [])
        spec['scenario']['id'] = SURVEY_SCENARIO_ID
        spec['questions'] = SURVEY_QUESTIONS
        with sqlite3.connect(self.path) as db:
            db.execute('UPDATE run SET spec=?', (json.dumps(spec),))
        old = response_report(self.path, self.people, snapshot=self.snapshot)
        self.assertEqual(len(old['questions']), 8)
        self.assertEqual(old['questions'][0]['domain'], 'need')
        self.assertNotIn('consider', next(question['choices'] for question in old['questions'] if question['domain'] == 'usage'))
        self.assertTrue(all(person['items'][1]['fair_price']['choice'] == 'pending' for person in old['people']))


if __name__ == '__main__':
    unittest.main()
