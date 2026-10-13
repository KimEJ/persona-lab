"""Settings imports recreate editable inputs without restoring run state."""
import copy
import json
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

import test_sampling_flow as fixtures
from persona_desktop.application import atomic_json
from persona_desktop.documents import valuation_from_fields
from persona_desktop.server import make_server
from persona_lab.contracts import ContractError
from persona_lab.responses import SURVEY_V2_SCENARIO_ID
from persona_lab.runner import selected_personas
from persona_lab.tags import canonical_tag_id


class SettingsImportTests(unittest.TestCase):
    setUp = fixtures.SamplingFlowTests.setUp
    write_pack = fixtures.SamplingFlowTests.write_pack

    def settings(self):
        currencies = [('JPY', '2000', ['500', '1000', '2000']),
                      ('KRW', '9900', ['1000', '5000', '10000']),
                      ('USD', '9.99', ['2.49', '9.99', '19.99']),
                      ('EUR', '14.50', ['4.99', '14.50', '29.99'])]
        items = [{'id': f'{index + 1:032x}', 'name': f'메모 상품 {currency}',
                  'document': f'# 메모 상품 {currency}\n검색·태그로 문서를 정리합니다. 日本語も保存。\n',
                  'pricing': {'state': 'paid', 'amount': amount, 'currency': currency,
                              'billing': ('one_time', 'monthly', 'annual')[index % 3]},
                  'valuation': {'mode': 'auto' if index == 0 else 'manual',
                                'currency': currency, 'billing': 'monthly',
                                'boundaries': ['', '', ''] if index == 0 else boundaries}}
                 for index, (currency, amount, boundaries) in enumerate(currencies)]
        items.append({'id': '5'*32, 'name': '무료 상품', 'document': '무료로 문서를 공유합니다.',
                      'pricing': {'state': 'free', 'amount': '0', 'currency': 'JPY', 'billing': 'one_time'},
                      'valuation': {'mode': 'manual', 'currency': 'JPY', 'billing': 'one_time',
                                    'boundaries': ['', '', '']}})
        return {'id': 'a'*32, 'title': '가격 비교 · 日本語', 'workflow': SURVEY_V2_SCENARIO_ID,
                'items': items, 'panel': {'selection': 'random', 'sample_size': 2,
                'sample_seed': 481, 'sampling_version': 'hash-rank-v1', 'sex': 'female',
                'age_min': 24, 'age_max': 36, 'prefecture': '東京都', 'query': '작가'},
                'settings': {'seed': 123, 'repeats': 3}}

    def cohort(self, panel):
        return [person.uuid for person in selected_personas(self.app.people, panel)]

    def assert_fresh(self, imported, original):
        self.assertNotEqual(imported['id'], original['id'])
        self.assertEqual(imported['revision'], 0)
        self.assertIsNone(imported['run'])
        self.assertEqual({path.name for path in self.app.directory(imported['id']).iterdir()}, {'draft.json'})
        self.assertTrue({item['id'] for item in imported['items']}.isdisjoint(item['id'] for item in original['items']))
        self.assertEqual(len({item['id'] for item in imported['items']}), len(imported['items']))

    def test_editable_round_trip_preserves_all_inputs_and_redraw_seed(self):
        original = self.settings()
        untouched = copy.deepcopy(original)
        imported = self.app.import_settings(original)
        self.assert_fresh(imported, original)
        for key in ('title', 'workflow', 'panel', 'settings'):
            self.assertEqual(imported[key], original[key])
        for actual, expected in zip(imported['items'], original['items']):
            self.assertEqual({key: value for key, value in actual.items() if key != 'id'},
                             {key: value for key, value in expected.items() if key != 'id'})
        self.assertEqual(self.cohort(imported['panel']), self.cohort(original['panel']))
        self.assertEqual(original, untouched)
        imported['title'] = '가져온 뒤 수정'
        saved = self.app.save(imported['id'], imported)
        self.assertEqual((saved['title'], saved['revision']), ('가져온 뒤 수정', 1))

    def test_exported_replay_prefers_original_auto_settings_and_discards_run_resources(self):
        original = self.app.import_settings(self.settings())
        spec = copy.deepcopy(self.app.make_spec(original))
        spec['panel']['selected_uuids'] = self.cohort(spec['panel'])
        unit, bands = valuation_from_fields({'mode': 'manual', 'currency': 'JPY',
                                             'billing': 'monthly', 'boundaries': ['500', '1000', '2000']})
        spec['products'][0].update(valuation_unit=unit, valuation_bands=bands,
                                   valuation_calibration={'model_calls': '/never/read/model.sqlite'})
        frozen = {key: value for key, value in original.items() if key not in {'run', 'legacy_items', 'question_catalog'}}
        frozen['panel'] = copy.deepcopy(spec['panel'])
        snapshot = {'draft': frozen, 'spec': spec,
                    'source': {'data_file': '/never/read/data.jsonl'}, 'created_at': 'old-time',
                    'model_calls': [{'external_path': '/never/read/model.sqlite'}],
                    'results': [{'choice': 'buy'}], 'reviews': {'job': {'note': 'old note'}}}
        atomic_json(self.app.directory(original['id'])/'run.json', snapshot)
        exported = json.loads(self.app.export(original['id'], 'spec')[0])
        with patch.object(self.app, 'source_pack', side_effect=AssertionError('loaded external source')):
            imported = self.app.import_settings(exported)
        self.assert_fresh(imported, original)
        self.assertEqual(imported['items'][0]['valuation']['mode'], 'auto')
        self.assertEqual(imported['items'][0]['valuation']['boundaries'], ['', '', ''])
        self.assertEqual(imported['panel'], original['panel'])
        self.assertNotIn('selected_uuids', imported['panel'])
        self.assertEqual(self.cohort(imported['panel']), snapshot['spec']['panel']['selected_uuids'])

    def test_current_spec_and_wrapper_preserve_explicit_prices_and_manual_boundaries(self):
        original = self.app.import_settings(self.settings())
        spec = copy.deepcopy(self.app.make_spec(original))
        spec['panel']['selected_uuids'] = self.cohort(spec['panel'])
        for value in (spec, {'spec': spec, 'source': {'data_file': '/never/read'}}):
            with self.subTest(wrapped='spec' in value):
                imported = self.app.import_settings(value)
                self.assert_fresh(imported, original)
                self.assertEqual(imported['settings'], original['settings'])
                self.assertEqual(imported['panel'], original['panel'])
                restored = self.app.make_spec(imported)
                for actual, expected in zip(restored['products'], spec['products']):
                    for key in ('name', 'document', 'price', 'valuation_unit', 'valuation_bands'):
                        self.assertEqual(actual[key], expected[key])
                self.assertEqual(imported['items'][0]['valuation']['mode'], 'auto')
                self.assertEqual(imported['items'][2]['valuation']['boundaries'], ['2.49', '9.99', '19.99'])

    def test_selected_cohort_only_derives_size_and_all_filter_panels_use_current_pool(self):
        original = self.app.import_settings(self.settings())
        spec = self.app.make_spec(original)
        spec['panel'] = {'selected_uuids': self.cohort(original['panel'])}
        imported = self.app.import_settings(spec)
        self.assertEqual((imported['panel']['selection'], imported['panel']['sample_size'],
                          imported['panel']['sample_seed']), ('random', 2, spec['seed']))
        for panel in ({'selection': 'all'}, {'selection': 'filter', 'sex': 'female'}):
            spec['panel'] = panel
            expected = self.cohort(panel)
            imported = self.app.import_settings(spec)
            self.assertEqual(imported['panel']['sample_size'], len(expected))
            self.assertEqual(set(self.cohort(imported['panel'])), set(expected))

    def test_unfinished_editable_document_can_be_imported(self):
        value = self.settings()
        value.pop('workflow')
        value['items'] = [{'name': '', 'document': '', 'pricing': {'state': 'unset', 'amount': '',
                          'currency': 'USD', 'billing': 'annual'},
                          'valuation': {'mode': 'auto', 'currency': 'USD', 'billing': 'annual',
                                        'boundaries': ['', '', '']}}]
        imported = self.app.import_settings(value)
        self.assertIsNone(imported['run'])
        self.assertEqual(imported['items'][0]['pricing']['currency'], 'USD')
        self.assertEqual(imported['workflow'], SURVEY_V2_SCENARIO_ID)

    def test_tags_and_match_mode_survive_editable_replay_spec_and_copy(self):
        for person in self.app.people:
            person.raw['skills_and_expertise_list'] = '["Python"]'
            person.raw['hobbies_and_interests_list'] = '["독서"]'
        for mode in ('any', 'all', None):
            value = self.settings()
            value['panel']['tags'] = ['skill:python', 'interest:독서']
            if mode:
                value['panel']['tag_mode'] = mode
            imported = self.app.import_settings(value)
            expected = copy.deepcopy(imported['panel'])
            self.assertEqual(expected, value['panel'])
            copied = self.app.create(imported['id'])
            self.assertEqual(copied['panel'], expected)
            editable_export = json.loads(json.dumps({key: imported[key] for key in
                ('title', 'workflow', 'items', 'panel', 'settings')}, ensure_ascii=False))
            self.assertEqual(self.app.import_settings(editable_export)['panel'], expected)
            spec = copy.deepcopy(self.app.make_spec(imported))
            spec['panel']['selected_uuids'] = self.cohort(expected)
            frozen = {key: imported[key] for key in ('id', 'title', 'workflow', 'revision', 'updated_at', 'items', 'settings')}
            frozen['panel'] = copy.deepcopy(spec['panel'])
            atomic_json(self.app.directory(imported['id'])/'run.json',
                        {'draft': frozen, 'spec': spec, 'source': self.app.source})
            replay = json.loads(self.app.export(imported['id'], 'spec')[0])
            for exported in (replay, spec):
                restored = self.app.import_settings(exported)
                self.assertEqual(restored['panel'], expected)
                self.assertEqual(self.cohort(restored['panel']), spec['panel']['selected_uuids'])

    def test_invalid_settings_leave_existing_experiments_byte_identical(self):
        original = self.app.import_settings(self.settings())
        path = self.app.directory(original['id'])/'draft.json'
        before = path.read_bytes()
        identifiers = {directory.name for directory in self.app.experiments.iterdir()}
        invalid = [None, [], {}, {'draft': []}]
        for key, value in [('title', ''), ('title', 'x'*121), ('items', []), ('items', [None]),
                           ('items', self.settings()['items']*2), ('panel', []),
                           ('panel', {'selection': 'random', 'sample_size': 0, 'sample_seed': 1}),
                           ('settings', {'seed': True, 'repeats': 1}),
                           ('settings', {'seed': 1, 'repeats': 0}),
                           ('settings', {'seed': 1, 'repeats': 1, 'budget': 100})]:
            candidate = self.settings(); candidate[key] = value; invalid.append(candidate)
        for key, value in [('document', 'x'*20001), ('document', []), ('name', 'x'*121),
                           ('pricing', {'state': 'paid', 'amount': '9.999', 'currency': 'USD', 'billing': 'annual'}),
                           ('valuation', {'mode': 'manual', 'currency': 'USD', 'billing': 'monthly',
                                          'boundaries': ['10', '5', '20']})]:
            candidate = self.settings(); candidate['items'][0][key] = value; invalid.append(candidate)
        candidate = self.settings(); candidate['panel']['selected_uuids'] = ['old-person']; invalid.append(candidate)
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ContractError):
                self.app.import_settings(value)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual({directory.name for directory in self.app.experiments.iterdir()}, identifiers)

    def test_current_concept_ids_round_trip_without_rewriting_legacy_ids_or_locale(self):
        for person in self.app.people:
            person.raw['skills_and_expertise_list'] = '["Python", "文書作成"]'
            person.raw['hobbies_and_interests_list'] = '["독서"]'
        legacy = ['skill:文書作成', 'interest:독서']
        current = [canonical_tag_id(identifier) for identifier in legacy]
        self.assertTrue(all(':concept/' in identifier for identifier in current))
        expected = None
        for identifiers in (legacy, current):
            value = self.settings()
            value['panel'].update(tags=identifiers, tag_mode='all')
            imported = self.app.import_settings(value)
            self.assertEqual(imported['panel']['tags'], identifiers)
            if expected is None:
                expected = self.cohort(imported['panel'])
            self.assertEqual(self.cohort(imported['panel']), expected)
            editable = json.loads(json.dumps({key: imported[key] for key in
                ('title', 'workflow', 'items', 'panel', 'settings')}))
            self.assertEqual(self.app.import_settings(editable)['panel']['tags'], identifiers)
            spec = copy.deepcopy(self.app.make_spec(imported))
            spec['panel']['selected_uuids'] = expected
            restored = self.app.import_settings(spec)
            self.assertEqual(restored['panel']['tags'], identifiers)
            self.assertEqual(self.cohort(restored['panel']), expected)
            reply = self.app.panel_tags(restored['panel'], locale='ja')
            self.assertEqual([tag['id'] for tag in reply['selected']], identifiers)
            self.assertNotIn('tag_locale', self.app.get(restored['id'])['panel'])

    def test_unsupported_legacy_workflows_are_rejected_and_write_failure_is_atomic(self):
        original = self.app.import_settings(self.settings())
        spec = self.app.make_spec(original)
        paths = {path: path.read_bytes() for path in self.app.experiments.glob('*/draft.json')}
        for workflow in ('product-survey-v1', 'product-response-v2', 'legacy', ['invalid']):
            draft = self.settings(); draft['workflow'] = workflow
            legacy_spec = copy.deepcopy(spec); legacy_spec['scenario']['id'] = workflow
            for value in (draft, legacy_spec, {'draft': self.settings(), 'spec': legacy_spec}):
                with self.subTest(workflow=workflow), self.assertRaisesRegex(ContractError, '이전 버전'):
                    self.app.import_settings(value)
        with patch('persona_desktop.application.atomic_json', side_effect=OSError('disk write failure')):
            with self.assertRaises(OSError):
                self.app.import_settings(self.settings())
        self.assertEqual({path: path.read_bytes() for path in self.app.experiments.glob('*/draft.json')}, paths)
        self.assertFalse(list(self.app.home.glob('.settings-import-*')))

    def test_http_import_returns_new_draft_and_malformed_input_does_not_create_one(self):
        server = make_server(self.app)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        base = f'http://127.0.0.1:{server.server_address[1]}'
        def call(value):
            request = urllib.request.Request(base+'/api/experiments/import',
                data=json.dumps({'settings': value}, ensure_ascii=False).encode(),
                headers={'X-Persona-Token': server.token, 'Content-Type': 'application/json'})
            return urllib.request.urlopen(request, timeout=5)
        try:
            with call(self.settings()) as response:
                self.assertEqual(response.status, 201)
                imported = json.load(response)
                self.assertIsNone(imported['run'])
            with self.assertRaises(urllib.error.HTTPError) as caught:
                call({'draft': []})
            self.assertEqual(caught.exception.code, 400)
            self.assertEqual(len(self.app.history()), 1)
        finally:
            server.shutdown(); server.server_close(); thread.join(2)


if __name__ == '__main__':
    unittest.main()
