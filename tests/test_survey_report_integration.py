"""Bounded integration checks for independent surveys and frozen report scope."""
import copy
import csv
import io
import json
import sqlite3
import threading
import unittest
import urllib.request
from unittest.mock import patch

import test_sampling_flow as fixtures
from persona_desktop.application import atomic_json
from persona_desktop.server import make_server
from persona_lab.backends import FixtureBackend
from persona_lab.contracts import ContractError, Decision
from persona_lab.finite_decision import ClefBackend
from persona_lab.responses import SURVEY_V2_SCENARIO_ID, SURVEY_V3_SCENARIO_ID
from persona_lab.survey import SURVEY_V2_DOMAINS, SURVEY_V3_DOMAINS, SURVEY_V3_QUESTIONS


class SurveyReportIntegrationTests(unittest.TestCase):
    setUp = fixtures.SamplingFlowTests.setUp
    write_pack = fixtures.SamplingFlowTests.write_pack
    finish = fixtures.SamplingFlowTests.finish

    def configure(self, count=1, items=1, repeats=1, grid=True):
        draft = fixtures.SamplingFlowTests.configure(self, self.app.create(), count, items, repeats)
        draft['title'] = '고정된 제품 설문'
        for item in draft['items']:
            item['valuation'] = {'currency': 'JPY', 'billing': 'one_time',
                                 'boundaries': ['500', '1500', '3000'] if grid else ['', '', '']}
        return self.app.save(draft['id'], draft)

    def test_grouped_choices_preserve_nine_results_and_derive_acceptance_without_a_call(self):
        draft = self.configure(items=2)
        draft['items'][1]['pricing']['state'] = 'free'
        draft = self.app.save(draft['id'], draft)
        observed, wires = [], []

        class Observe(ClefBackend):
            def decide_batch(inner, batch):
                observed.extend(batch)
                return super().decide_batch(batch)

        backend = Observe(survey_version=SURVEY_V3_SCENARIO_ID, inference_protocol='survey-grouped-v2',
                          survey_questions=SURVEY_V3_QUESTIONS)
        self.app.test_backend = backend

        def reply(request, **kwargs):
            self.assertTrue(request.full_url.endswith('/v1/systemone'))
            wires.append(request.data.decode())
            body = json.loads(request.data)
            answers = {}
            for question_id, question in body['questions'].items():
                options = question['criteria']
                choice = 'consider' if 'consider' in options else 'decline' if 'decline' in options else next(iter(options))
                answers[question_id] = {'type': 'choice', 'choice': choice,
                                        'probabilities': {key: float(key == choice) for key in options}}
            answer = {'answers': answers,
                      'usage': {'input_tokens': 10, 'output_tokens': 0}}
            return io.BytesIO(json.dumps(answer).encode())

        with patch('urllib.request.urlopen', side_effect=reply):
            self.app.start(draft['id'])
            status = self.finish(draft['id'])
        self.assertEqual((status['cursor'], status['backend_errors']), (18, 0))
        self.assertEqual({job.question['domain'] for job in observed}, set(SURVEY_V3_DOMAINS))
        self.assertTrue(all(job.assessments is None for job in observed))
        directory = self.app.directory(draft['id'])
        with sqlite3.connect(directory / 'run.sqlite') as db:
            records = [json.loads(row[0]) for row in db.execute('SELECT payload FROM results ORDER BY ordinal')]
            calls = db.execute('SELECT job_id,request,response,error FROM model_calls ORDER BY id').fetchall()
            by_job = dict(db.execute('SELECT links.job_id,calls.request FROM model_call_jobs links JOIN model_calls calls ON calls.id=links.call_id'))
        self.assertEqual([call[1] for call in calls], wires)
        self.assertEqual(len(calls), 4)
        self.assertEqual(set(by_job), {record['job_id'] for record in records})
        self.assertTrue(all(response and error is None for _, _, response, error in calls))
        for record in records:
            wire = by_job[record['job_id']]
            self.assertNotIn('assessments', record)
            self.assertEqual(record['decision']['reason'], '')
            self.assertFalse(any(ref.startswith('assessments.') for ref in record['decision']['evidence_refs']))
            state = json.loads(json.loads(wire)['state'])
            self.assertNotIn('prior_assessments', state)
            self.assertNotIn('assessments', state)
            self.assertNotIn('offer', state)
            self.assertEqual('valuation_bands' in state, record['domain'] == 'fair_price')
        response = self.app.responses(draft['id'])
        self.assertEqual(response['workflow'], SURVEY_V3_SCENARIO_ID)
        self.assertEqual([band['low_minor'] for band in response['products'][0]['valuation_bands']], [0, 500, 1500, 3000])
        items = response['people'][0]['items']
        self.assertTrue(all(item['usage']['choice'] == 'consider' and item['acceptance']['derived']
                            and 'purchase' not in item for item in items))
        self.assertEqual([item['acceptance']['choice'] for item in items], ['reject', 'defer'])
        exported = json.loads(self.app.export(draft['id'], 'json')[0])
        self.assertEqual(len(exported['model_calls']), 4)
        self.assertEqual(len(exported['model_call_jobs']), 18)
        self.assertEqual({link['job_id'] for link in exported['model_call_jobs']}, set(by_job))

    def test_report_api_and_exports_use_one_frozen_repeat_and_the_same_denominator(self):
        draft = self.configure(count=3, items=2, repeats=2)
        # This frozen v2 report preserves the historical final-choice contract.
        draft['workflow'] = SURVEY_V2_SCENARIO_ID
        atomic_json(self.app.directory(draft['id']) / 'run.json', {
            'draft': {key: value for key, value in draft.items()
                      if key not in {'run', 'legacy_items', 'question_catalog'}},
            'spec': self.app.make_spec(draft), 'source': self.app.source,
            'created_at': 'frozen-test-time'})

        class PerRepeat(FixtureBackend):
            def decide(inner, job):
                if job.question['domain'] not in {'usage', 'purchase'}:
                    return super().decide(job)
                choice = ('use', 'consider')[job.repeat] if job.question['domain'] == 'usage' else ('buy', 'decline')[job.repeat]
                return Decision(choice, 'ok', ('fixture_response_rule',), ('product.document',),
                                evidence_semantics='supplied_input_only',
                                option_probabilities={key: float(key == choice) for key in job.question['choices'] if key != 'not_run'},
                                probability_semantics='model_option_distribution')

        self.app.test_backend = PerRepeat()
        self.app.start(draft['id'])
        self.assertEqual(self.finish(draft['id'])['cursor'], 120)
        snapshot = self.app.snapshot(draft['id'])
        directory = self.app.directory(draft['id'])
        changed = json.loads((directory / 'draft.json').read_text())
        changed['title'] = '실행 뒤 변경한 초안'
        changed['items'][0].update(name='변경한 상품', document='변경한 문서')
        changed['panel']['sex'] = 'male'
        atomic_json(directory / 'draft.json', changed)
        server = make_server(self.app)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def call(suffix, body=None):
            request = urllib.request.Request(f'http://127.0.0.1:{server.server_address[1]}/api/experiments/{draft["id"]}/{suffix}',
                                             data=json.dumps(body).encode() if body is not None else None,
                                             headers={'X-Persona-Token': server.token, 'Content-Type': 'application/json'})
            with urllib.request.urlopen(request, timeout=3) as response:
                return json.load(response)

        try:
            report = call('report?repeat=1')
            response = report['responses']
            self.assertEqual(response, call('responses?repeat=1'))
            self.assertEqual((response['count'], response['repeat'], response['repeats']), (3, 1, 2))
            self.assertEqual(report['report_context']['title'], draft['title'])
            self.assertEqual(report['report_context']['panel'], snapshot['spec']['panel'])
            self.assertEqual(report['report_context']['products'][0]['document'], fixtures.DOCUMENT)
            self.assertEqual(len(response['statistics']), 20)
            for data in response['statistics']:
                self.assertEqual((data['denominator'], sum(data['counts'].values())), (3, 3))
                self.assertAlmostEqual(sum(data['shares'].values()), 1)
                if data['domain'] == 'purchase':
                    self.assertEqual((data['counts']['decline'], data['counts']['buy']), (3, 0))
                if data['domain'] == 'usage':
                    self.assertEqual(data['counts']['consider'], 3)
            first = call('report?repeat=0')['responses']
            self.assertTrue(all(item['purchase']['choice'] == 'buy' for person in first['people'] for item in person['items']))
            exported = {format: call('export', {'format': format, 'repeat': 1}) for format in ('json', 'csv', 'md', 'html', 'pdf')}
            self.assertEqual(json.loads(exported['json']['body'])['responses'], response)
            rows = list(csv.DictReader(io.StringIO(exported['csv']['body'])))
            self.assertEqual({(row['repeat'], row['selected_people_denominator']) for row in rows}, {('1', '3')})
            self.assertEqual(sum(int(row['count']) for row in rows), 60)
            self.assertTrue(all(int(row['count']) == 3 for row in rows if row['domain'] == 'purchase' and row['choice'] == 'decline'))
            for format in ('md', 'html', 'pdf'):
                self.assertIn('회차 2/2', exported[format]['body'])
                self.assertIn(draft['title'], exported[format]['body'])
                self.assertNotIn(changed['title'], exported[format]['body'])
            self.assertIn('| 3 | 3 | 100.0% |', exported['md']['body'])
            self.assertIn('구매하지 않음 3명', exported['html']['body'])
            self.assertEqual(exported['html']['body'], exported['pdf']['body'])
            self.assertEqual(exported['pdf']['mime'], 'text/html; charset=utf-8')
            self.assertTrue(all(value['filename'].endswith('-r2.' + format) for format, value in exported.items()))
            with self.assertRaises(ContractError):
                self.app.report(draft['id'], 2)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)

    def test_invalid_grid_cannot_freeze_and_missing_grid_or_offer_remain_unavailable(self):
        draft = self.configure(grid=False)
        directory = self.app.directory(draft['id'])
        for boundaries in (['500', '', '3000'], ['500', '500', '3000'], ['1500', '500', '3000'], ['0.5', '1500', '3000']):
            candidate = copy.deepcopy(draft)
            candidate['items'][0]['valuation']['boundaries'] = boundaries
            with self.subTest(boundaries=boundaries), self.assertRaises(ContractError):
                self.app.save(draft['id'], candidate)
            self.assertFalse((directory / 'run.json').exists())
        stored = (directory / 'draft.json').read_bytes()
        atomic_json(directory / 'draft.json', candidate)
        with self.assertRaises(ContractError):
            self.app.start(draft['id'])
        self.assertIsNone(self.app.status(draft['id']))
        self.assertFalse((directory / 'run.json').exists())
        (directory / 'draft.json').write_bytes(stored)
        draft['items'][0]['pricing']['state'] = 'unset'
        draft = self.app.save(draft['id'], draft)
        observed = []

        class Observe(FixtureBackend):
            def decide(inner, job):
                observed.append(job.question['domain'])
                if job.question['domain'] == 'usage':
                    return Decision('use', 'ok', ('fixture_response_rule',), ('product.document',),
                                    evidence_semantics='supplied_input_only',
                                    option_probabilities={key: float(key == 'use') for key in job.question['choices']},
                                    probability_semantics='model_option_distribution')
                return super().decide(job)

        self.app.test_backend = Observe()
        self.app.start(draft['id'])
        status = self.finish(draft['id'])
        self.assertEqual((status['cursor'], status['backend_errors']), (9, 0))
        self.assertEqual(set(observed), set(SURVEY_V3_DOMAINS) - {'fair_price'})
        response = self.app.responses(draft['id'])
        item = response['people'][0]['items'][0]
        for domain, missing in [('fair_price', '평가 가격대'), ('acceptance', '판매가격')]:
            self.assertEqual((item[domain]['choice'], item[domain]['status']), ('not_run', 'not_run'))
            self.assertEqual(item[domain]['missing_information'], [missing])
            stat = next(data for data in response['statistics'] if data['domain'] == domain)
            self.assertEqual((stat['counts']['not_run'], stat['counts']['unknown'], stat['evaluated']), (1, 0, 0))


if __name__ == '__main__':
    unittest.main()
