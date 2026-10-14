"""Bounded application checks: separate preparation, journals and immutable runs."""
import copy
import io
import json
import sqlite3
import threading
import unittest
from unittest.mock import patch

import test_sampling_flow as fixtures
from persona_desktop.application import Application
from persona_lab.backends import FixtureBackend
from persona_lab.contracts import ContractError
from persona_lab.finite_decision import ClefBackend
from persona_lab.responses import SURVEY_V4_SCENARIO_ID
from persona_lab.survey import SURVEY_V4_QUESTIONS


class AutoPriceIntegrationTests(unittest.TestCase):
    setUp = fixtures.SamplingFlowTests.setUp
    write_pack = fixtures.SamplingFlowTests.write_pack
    finish = fixtures.SamplingFlowTests.finish

    def configure(self, items=1):
        draft = self.app.create()
        self.assertEqual(draft['items'][0]['valuation']['mode'], 'auto')
        first = draft['items'][0]
        first.update(name='문서 정리 도구', document='## 주요 기능\n태그와 검색으로 문서를 정리합니다.\n')
        first['pricing'].update(state='paid', amount='2000')
        draft['items'] = [{**copy.deepcopy(first), 'id': f'{index+1:032x}',
                           'pricing': {**first['pricing'], 'amount': str(2000+index*1000)}}
                          for index in range(items)]
        draft['panel']['sample_size'] = 2
        return self.app.save(draft['id'], draft)

    @staticmethod
    def reply(request, **kwargs):
        body = json.loads(request.data)
        state = json.loads(body['state'])
        answers = {}
        for question_id, question in body['questions'].items():
            if 'valuation_bands' in state:
                choice = next(band['id'] for band in state['valuation_bands']
                              if band['low_minor'] <= 1500 and (band['high_minor'] is None or 1500 <= band['high_minor']))
            else:
                choice = next(option for option in question['criteria'] if option not in {'unknown', 'not_run'})
            answers[question_id] = {'type': 'choice', 'choice': choice,
                                    'probabilities': {key: float(key == choice) for key in question['criteria']}}
        return io.BytesIO(json.dumps({'answers': answers,
                                     'usage': {'input_tokens': 20, 'output_tokens': 0}}).encode())

    def test_automatic_grid_and_raw_journal_are_frozen_before_the_main_run(self):
        draft = self.configure(items=2)
        self.app.test_backend = ClefBackend(survey_version=SURVEY_V4_SCENARIO_ID, inference_protocol='survey-staged-v1',
                                           survey_questions=SURVEY_V4_QUESTIONS)
        with patch('persona_lab.finite_decision.urllib.request.urlopen', side_effect=self.reply):
            self.app.start(draft['id'])
            status = self.finish(draft['id'])
            self.assertEqual((status['cursor'], status['total'], status['backend_errors']), (36, 36, 0))
            directory = self.app.directory(draft['id'])
            self.assertFalse((directory/'preparation.json').exists())
            frozen = (directory/'run.json').read_bytes()
            snapshot = json.loads(frozen)
            products = snapshot['spec']['products']
            self.assertEqual(products[0]['valuation_bands'], products[1]['valuation_bands'])
            self.assertEqual(products[1]['valuation_calibration']['reused_from'], products[0]['id'])
            self.assertTrue(snapshot['price_calibration']['complete'])
            self.assertEqual(snapshot['price_calibration']['algorithm_version'], 'auto-wtp-v3')
            self.assertEqual(snapshot['spec']['scenario']['id'], SURVEY_V4_SCENARIO_ID)
            self.assertEqual(snapshot['price_calibration']['scenario_id'], SURVEY_V4_SCENARIO_ID)
            self.assertEqual(len(snapshot['spec']['questions']), 9)
            self.assertNotIn('purchase', {question['domain'] for question in snapshot['spec']['questions']})
            pilot_ids = snapshot['price_calibration']['products'][products[0]['id']]['pilot_uuids']
            self.assertFalse(set(pilot_ids) & set(snapshot['spec']['panel']['selected_uuids']))
            with sqlite3.connect(directory/'price-calibration.sqlite') as db:
                calls = db.execute('SELECT request,response FROM model_calls').fetchall()
            self.assertEqual(len(calls), snapshot['price_calibration']['completed'])
            histories = []
            for request, response in calls:
                body = json.loads(request)
                self.assertEqual(len(body['questions']), 1)
                self.assertIn('지불할 의향이 있는 최대 가격', next(iter(body['questions'].values()))['instructions'])
                supplied = json.loads(body['state'])
                self.assertNotIn('offer', supplied)
                self.assertNotIn('prior_assessments', supplied)
                histories.append(supplied.get('price_decision_history'))
                self.assertIsNotNone(response)
            self.assertTrue(any(histories))
            with sqlite3.connect(directory/'run.sqlite') as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM results').fetchone()[0], 36)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM model_calls').fetchone()[0], 12)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM model_call_jobs').fetchone()[0], 36)
                self.assertEqual(json.loads(db.execute('SELECT spec FROM run').fetchone()[0]), snapshot['spec'])
                main_requests = db.execute('SELECT request FROM model_calls').fetchall()
                self.assertTrue(all('price_decision_history' not in json.loads(json.loads(request)['state'])
                                    for request, in main_requests))
                stage_inputs = [(len(json.loads(request)['questions']),
                                 len(json.loads(json.loads(request)['state']).get('survey_decision_history', {}).get('records', [])))
                                for request, in main_requests]
                self.assertEqual(stage_inputs, [(7, 0), (1, 7), (1, 8)] * 4)
                for request, in main_requests:
                    supplied = json.loads(json.loads(request)['state'])
                    history = supplied.get('survey_decision_history')
                    if history is not None:
                        self.assertEqual(history['protocol'], 'survey-history-v1')
                        self.assertTrue(all('job_id' not in record for record in history['records']))
                    if history is None or len(history['records']) == 7:
                        self.assertNotIn('valuation_bands', supplied)
            report = self.app.report(draft['id'])
            self.assertEqual(report['responses']['count'], 2)
            self.assertEqual(len(report['responses']['price_points']), 1)
            exported = json.loads(self.app.export(draft['id'], 'json')[0])
            self.assertEqual(len(exported['price_calibration_calls']), len(calls))
            self.assertEqual(exported['price_calibration'], snapshot['price_calibration'])
            with patch('persona_desktop.application.calibrate', side_effect=AssertionError('recalibrated frozen run')):
                self.app.start(draft['id'])
                self.finish(draft['id'])
            self.assertEqual((directory/'run.json').read_bytes(), frozen)

    def test_cancel_and_reopen_resume_the_preparation_checkpoint(self):
        draft = self.configure()
        entered, release = threading.Event(), threading.Event()

        class Blocking(FixtureBackend):
            def __init__(inner): inner.calls = 0
            def decide(inner, job):
                inner.calls += 1
                if inner.calls == 1:
                    entered.set()
                    if not release.wait(5): raise RuntimeError('test request timed out')
                return super().decide(job)

        backend = Blocking(); self.app.test_backend = backend
        self.app.start(draft['id'])
        try:
            self.assertTrue(entered.wait(5))
            status = self.app.status(draft['id'])
            self.assertEqual((status['status'], status['phase']), ('calibrating', 'price_calibration'))
            with self.assertRaises(ContractError): self.app.save(draft['id'], draft)
            self.app.cancel(draft['id'])
        finally: release.set()
        self.assertEqual(self.finish(draft['id'])['status'], 'paused')
        directory = self.app.directory(draft['id'])
        self.assertFalse((directory/'run.json').exists())
        self.assertFalse((directory/'run.sqlite').exists())
        prepared = self.app.snapshot(draft['id'])
        self.assertEqual(prepared['price_calibration']['completed'], 1)
        first_outcome = prepared['price_calibration']['products'][draft['items'][0]['id']]['rounds'][0]['outcomes'][0]
        self.app.close()
        self.app = Application(self.root, self.home, backend)
        self.assertEqual(self.app.get(draft['id'])['run']['status'], 'interrupted')
        self.app.start(draft['id']); status = self.finish(draft['id'])
        self.assertEqual((status['cursor'], status['backend_errors']), (18, 0))
        final = self.app.snapshot(draft['id'])
        self.assertEqual(final['price_calibration']['products'][draft['items'][0]['id']]['rounds'][0]['outcomes'][0], first_outcome)
        self.assertEqual(backend.calls, final['price_calibration']['completed'] + 18)

    def test_unavailable_warmup_preserves_the_other_measurements_and_legacy_manual_skip(self):
        draft = self.configure()
        draft['panel'].update(sample_size=1, age_min=20, age_max=22)
        draft = self.app.save(draft['id'], draft)
        self.app.start(draft['id']); status = self.finish(draft['id'])
        self.assertEqual((status['cursor'], status['backend_errors']), (9, 0))
        product = self.app.snapshot(draft['id'])['spec']['products'][0]
        self.assertEqual(product['valuation_calibration']['status'], 'unavailable')
        self.assertEqual(product['valuation_bands'], [])
        person = self.app.report(draft['id'])['responses']['people'][0]['items'][0]
        self.assertEqual(person['fair_price']['choice'], 'not_run')
        self.assertEqual(person['fair_price']['reason'], product['valuation_calibration']['reason'])
        self.assertEqual(person['fair_price']['missing_information'], [])
        self.assertNotEqual(person['usage']['choice'], 'not_run')
        self.assertNotIn('purchase', person)
        self.assertTrue(person['acceptance']['derived'])
        legacy = self.app.create(draft['id'])
        legacy['items'][0]['valuation'] = {'currency': 'JPY', 'billing': 'one_time', 'boundaries': ['', '', '']}
        legacy = self.app.save(legacy['id'], legacy)
        with patch('persona_desktop.application.calibrate', side_effect=AssertionError('legacy grid reinterpreted')):
            self.app.start(legacy['id']); self.finish(legacy['id'])
        self.assertNotIn('price_calibration', self.app.snapshot(legacy['id']))

    def test_state_polling_and_snapshot_reads_survive_preparation_promotion(self):
        draft = self.configure()
        self.app.test_backend = ClefBackend(survey_version=SURVEY_V4_SCENARIO_ID, inference_protocol='survey-staged-v1',
                                           survey_questions=SURVEY_V4_QUESTIONS)
        stop = threading.Event()
        failures, observations = [], []
        def poll():
            try:
                while not stop.wait(.001):
                    observations.append(self.app.state()['history'][0]['run']['status'])
                    self.assertEqual(self.app.snapshot(draft['id'])['draft']['id'], draft['id'])
            except Exception as error: failures.append(error)
        def slow_reply(request, **kwargs):
            threading.Event().wait(.002)
            return self.reply(request, **kwargs)
        with patch('persona_lab.finite_decision.urllib.request.urlopen', side_effect=slow_reply):
            self.app.start(draft['id'])
            reader = threading.Thread(target=poll); reader.start()
            try: self.finish(draft['id'])
            finally: stop.set(); reader.join(5)
        self.assertFalse(reader.is_alive())
        self.assertFalse(failures, failures)
        self.assertTrue(observations)
        self.assertEqual(self.app.status(draft['id'])['status'], 'completed')


if __name__ == '__main__': unittest.main()
