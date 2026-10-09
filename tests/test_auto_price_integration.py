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
from persona_lab.responses import SURVEY_V2_SCENARIO_ID


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
        question_id, question = next(iter(body['questions'].items()))
        state = json.loads(body['state'])
        if 'valuation_bands' in state:
            choice = next(band['id'] for band in state['valuation_bands']
                          if band['low_minor'] <= 1500 and (band['high_minor'] is None or 1500 <= band['high_minor']))
        else:
            choice = next(option for option in question['criteria'] if option not in {'unknown', 'not_run'})
        return io.BytesIO(json.dumps({'answers': {question_id: {'type': 'choice', 'choice': choice,
                                      'probabilities': {key: float(key == choice) for key in question['criteria']}}},
                                     'usage': {'input_tokens': 20, 'output_tokens': 0}}).encode())

    def test_automatic_grid_and_raw_journal_are_frozen_before_the_main_run(self):
        draft = self.configure(items=2)
        self.app.test_backend = ClefBackend(survey_version=SURVEY_V2_SCENARIO_ID)
        with patch('persona_lab.finite_decision.urllib.request.urlopen', side_effect=self.reply):
            self.app.start(draft['id'])
            status = self.finish(draft['id'])
            self.assertEqual((status['cursor'], status['total'], status['backend_errors']), (40, 40, 0))
            directory = self.app.directory(draft['id'])
            self.assertFalse((directory/'preparation.json').exists())
            frozen = (directory/'run.json').read_bytes()
            snapshot = json.loads(frozen)
            products = snapshot['spec']['products']
            self.assertEqual(products[0]['valuation_bands'], products[1]['valuation_bands'])
            self.assertEqual(products[1]['valuation_calibration']['reused_from'], products[0]['id'])
            self.assertTrue(snapshot['price_calibration']['complete'])
            pilot_ids = snapshot['price_calibration']['products'][products[0]['id']]['pilot_uuids']
            self.assertFalse(set(pilot_ids) & set(snapshot['spec']['panel']['selected_uuids']))
            with sqlite3.connect(directory/'price-calibration.sqlite') as db:
                calls = db.execute('SELECT request,response FROM model_calls').fetchall()
            self.assertEqual(len(calls), snapshot['price_calibration']['completed'])
            for request, response in calls:
                supplied = json.loads(json.loads(request)['state'])
                self.assertNotIn('offer', supplied)
                self.assertNotIn('prior_assessments', supplied)
                self.assertIsNotNone(response)
            with sqlite3.connect(directory/'run.sqlite') as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM results').fetchone()[0], 40)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM model_calls').fetchone()[0], 40)
                self.assertEqual(json.loads(db.execute('SELECT spec FROM run').fetchone()[0]), snapshot['spec'])
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
        self.assertEqual((status['cursor'], status['backend_errors']), (20, 0))
        final = self.app.snapshot(draft['id'])
        self.assertEqual(final['price_calibration']['products'][draft['items'][0]['id']]['rounds'][0]['outcomes'][0], first_outcome)
        self.assertEqual(backend.calls, final['price_calibration']['completed'] + 20)

    def test_unavailable_warmup_preserves_the_other_measurements_and_legacy_manual_skip(self):
        draft = self.configure()
        draft['panel'].update(sample_size=1, age_min=20, age_max=22)
        draft = self.app.save(draft['id'], draft)
        self.app.start(draft['id']); status = self.finish(draft['id'])
        self.assertEqual((status['cursor'], status['backend_errors']), (10, 0))
        product = self.app.snapshot(draft['id'])['spec']['products'][0]
        self.assertEqual(product['valuation_calibration']['status'], 'unavailable')
        self.assertEqual(product['valuation_bands'], [])
        person = self.app.report(draft['id'])['responses']['people'][0]['items'][0]
        self.assertEqual(person['fair_price']['choice'], 'not_run')
        self.assertEqual(person['fair_price']['reason'], product['valuation_calibration']['reason'])
        self.assertEqual(person['fair_price']['missing_information'], [])
        self.assertNotEqual(person['usage']['choice'], 'not_run')
        self.assertNotEqual(person['purchase']['choice'], 'not_run')
        legacy = self.app.create(draft['id'])
        legacy['items'][0]['valuation'] = {'currency': 'JPY', 'billing': 'one_time', 'boundaries': ['', '', '']}
        legacy = self.app.save(legacy['id'], legacy)
        with patch('persona_desktop.application.calibrate', side_effect=AssertionError('legacy grid reinterpreted')):
            self.app.start(legacy['id']); self.finish(legacy['id'])
        self.assertNotIn('price_calibration', self.app.snapshot(legacy['id']))

    def test_state_polling_and_snapshot_reads_survive_preparation_promotion(self):
        draft = self.configure()
        self.app.test_backend = ClefBackend(survey_version=SURVEY_V2_SCENARIO_ID)
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
