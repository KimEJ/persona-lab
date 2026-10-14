"""Bounded tag recommendations follow profile filters without sampling bias."""
import copy
import hashlib
import json
import sqlite3
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

import test_sampling_flow as fixtures
from persona_desktop.application import Application, atomic_json
from persona_desktop.server import make_server
from persona_lab.backends import FixtureBackend
from persona_lab.contracts import ContractError
from persona_lab.tags import canonical_tag_id, tag_catalog


class PanelTagTests(unittest.TestCase):
    setUp = fixtures.SamplingFlowTests.setUp

    def write_pack(self, count, version):
        source = fixtures.SamplingFlowTests.write_pack(self, count, version)
        path = self.root/'assets/data'/source['data_file']
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        for index, row in enumerate(rows):
            row['skills_and_expertise_list'] = ['文書作成', '文書作成', f'도구 {index}']
            if index % 4 == 0:
                row['skills_and_expertise_list'].append('Python')
            if index % 2:
                row['skills_and_expertise_list'].append('Rust')
            row['skills_and_expertise_list'] = json.dumps(row['skills_and_expertise_list'], ensure_ascii=False)
            row['hobbies_and_interests_list'] = json.dumps(['독서', '산책' if index % 2 == 0 else '운동'])
            row['occupation'] = '작가' if index % 2 == 0 else '개발자'
        data = ''.join(json.dumps(row, ensure_ascii=False)+'\n' for row in rows).encode()
        path.write_bytes(data)
        source['local_sha256'] = hashlib.sha256(data).hexdigest()
        atomic_json(self.root/'assets/data/nemotron-japan-sample.json', source)
        return source

    @staticmethod
    def panel(**filters):
        return {'selection': 'random', 'sample_size': 1, 'sample_seed': 17, **filters}

    def test_top_recommendations_are_bounded_deterministic_and_count_people_once(self):
        result = self.app.panel_tags(self.panel())
        self.assertEqual(len(result['tags']), 16)
        self.assertGreater(result['total'], 16)
        self.assertEqual(result['total'], result['matched'])
        self.assertEqual(result['tags'], sorted(result['tags'], key=lambda tag: (-tag['count'], tag['id'])))
        document = self.app.panel_tags(self.panel(), query='文書作成')
        self.assertEqual(document['tags'][0]['count'], 20)
        self.assertEqual(self.app.panel_tags(self.panel())['tags'], result['tags'])
        selected = [tag['id'] for tag in result['tags'][:6]]
        remaining = self.app.panel_tags(self.panel(tags=selected))
        self.assertEqual(len(remaining['tags']), 16)
        self.assertEqual((remaining['total'], remaining['matched']), (result['total'], result['total']-6))
        self.assertTrue(set(selected).isdisjoint(tag['id'] for tag in remaining['tags']))
        self.assertNotIn('tags', self.app.state())

    def test_selected_tags_frozen_cohort_and_sampling_do_not_bias_recommendations(self):
        panel = self.panel(tags=['skill:python'], tag_mode='all', sex='female', age_min=24, age_max=36,
                           prefecture='東京都', query='작가', selected_uuids=['authored-person-004'])
        before = copy.deepcopy(panel)
        rust = self.app.panel_tags(panel, query='Rust')
        self.assertEqual((rust['matched'], rust['tags']), (0, []))
        common = self.app.panel_tags(panel, query='文書作成')
        self.assertEqual(common['tags'][0]['count'], 4)
        tool = self.app.panel_tags(panel, query='도구')
        self.assertEqual(tool['matched'], 4)
        unrestricted = self.app.panel_tags(self.panel(tags=['skill:does-not-exist'], tag_mode='all'), query='Python')
        self.assertEqual(unrestricted['tags'][0]['count'], 5)
        self.assertEqual(panel, before)

    def test_label_search_normalizes_case_width_hashtags_and_category_names(self):
        result = self.app.panel_tags(self.panel(), query='  ＃ＰＹＴＨＯＮ  ')
        self.assertEqual((result['matched'], result['tags'][0]['id']), (1, canonical_tag_id('skill:python')))
        for query, kind in (('기술', 'skill'), ('관심사', 'interest'), ('직업', 'occupation')):
            result = self.app.panel_tags(self.panel(), query=query)
            self.assertGreater(result['matched'], 0)
            self.assertTrue(all(tag['kind'] == kind for tag in result['tags']))
        self.assertEqual(self.app.panel_tags(self.panel(), query='missing tag')['matched'], 0)
        result = self.app.panel_tags(self.panel(query='개발자'), query='Python')
        self.assertEqual(result['matched'], 0)
        self.assertEqual(self.app.panel_tags(self.panel(), query='개발자')['tags'][0]['count'], 10)

    def test_filter_cache_is_reused_across_search_and_tag_selection_but_not_base_filters(self):
        with patch('persona_lab.tags.tag_catalog', wraps=tag_catalog) as catalog:
            self.app.panel_tags(self.panel(), query='Python')
            self.app.panel_tags(self.panel(tags=['skill:python'], tag_mode='all'), query='Rust')
            self.app.panel_tags(self.panel(sample_size=12, sample_seed=99), query='관심사')
            self.app.panel_tags(self.panel(), query='文書作成', locale='en')
            self.app.panel_tags(self.panel(), query='직업', locale='ja')
            self.assertEqual(catalog.call_count, 1)
            self.app.panel_tags(self.panel(prefecture='東京都'), query='Python')
            self.assertEqual(catalog.call_count, 2)
        result = self.app.panel_tags(self.panel(), query='Python')
        result['tags'][0]['count'] = 999
        self.assertEqual(self.app.panel_tags(self.panel(), query='Python')['tags'][0]['count'], 5)

    def test_locale_switch_keeps_catalog_ids_counts_and_multilingual_search(self):
        before = copy.deepcopy(self.panel())
        versions = {locale: self.app.panel_tags(before, query='文書作成', locale=locale)
                    for locale in ('ko', 'en', 'ja')}
        reference = versions['ko']['tags'][0]
        self.assertGreater(len(set(reference['labels'].values())), 1)
        for locale, result in versions.items():
            self.assertEqual((result['tag_locale'], result['tags'][0]['id'], result['tags'][0]['count']),
                             (locale, reference['id'], 20))
            self.assertEqual(result['tags'][0]['label'], reference['labels'][locale])
            self.assertEqual(set(result['tags'][0]['labels']), {'ko', 'en', 'ja'})
        for label in reference['labels'].values():
            result = self.app.panel_tags(before, query=label, locale='en')
            self.assertIn(reference['id'], [tag['id'] for tag in result['tags']])
        self.assertEqual(before, self.panel())
        self.assertEqual(self.app.panel_tags(before, query='skill:文書作成')['tags'][0]['id'], reference['id'])

    def test_selected_metadata_retains_legacy_absent_ids_and_excludes_equivalent_suggestions(self):
        legacy = 'skill:文書作成'
        current = canonical_tag_id(legacy)
        absent = canonical_tag_id('occupation:no-current-profile')
        panel = self.panel(tags=[legacy, absent], tag_mode='all')
        before = copy.deepcopy(panel)
        result = self.app.panel_tags(panel, query='文書作成', locale='en')
        self.assertEqual([tag['id'] for tag in result['selected']], [legacy, absent])
        self.assertTrue(all(set(tag['labels']) == {'ko', 'en', 'ja'} for tag in result['selected']))
        self.assertNotIn(current, [tag['id'] for tag in result['tags']])
        self.assertEqual(result['matched'], 0)
        self.assertEqual(panel, before)

    def test_unknown_selected_source_hash_keeps_its_label_outside_current_filters(self):
        original = self.app.panel_tags(self.panel(), query='도구 1')['tags']
        selected = next(tag for tag in original if tag['label'] == '도구 1')
        panel = self.panel(tags=[selected['id']], prefecture='東京都')
        result = self.app.panel_tags(panel, locale='en')
        self.assertEqual(result['selected'][0]['id'], selected['id'])
        self.assertEqual(result['selected'][0]['label'], '도구 1')

    def test_legacy_language_preferences_are_ignored_and_preserved_after_restart(self):
        path = self.app.home/'ui-preferences.json'
        self.assertEqual(self.app.state()['tag_locale'], 'ko')
        atomic_json(path, {'tag_locale': 'en', 'sidebar_width': 245})
        before = path.read_bytes()
        root, home = self.app.root, self.app.home
        self.app.close()
        self.app = Application(root, home, FixtureBackend())
        self.assertEqual(self.app.state()['tag_locale'], 'ko')
        tags = self.app.panel_tags(self.panel(), query='文書作成')
        self.assertEqual(tags['tag_locale'], 'ko')
        self.assertEqual(tags['tags'][0]['label'], tags['tags'][0]['labels']['ko'])
        self.assertEqual(path.read_bytes(), before)
        server = make_server(self.app)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        base = f'http://127.0.0.1:{server.server_address[1]}'
        def call(body):
            request = urllib.request.Request(base+'/api/preferences', data=json.dumps(body).encode(),
                headers={'X-Persona-Token': server.token, 'Content-Type': 'application/json'})
            return urllib.request.urlopen(request, timeout=5)
        try:
            with self.assertRaises(urllib.error.HTTPError) as caught:
                call({'tag_locale': 'ja'})
            self.assertEqual(caught.exception.code, 404)
            self.assertEqual(path.read_bytes(), before)
        finally:
            server.shutdown(); server.server_close(); thread.join(2)

    def test_report_and_responses_use_app_language_without_changing_frozen_fingerprint(self):
        draft = self.app.create()
        draft['items'][0].update(name='메모 도구', document='검색과 태그로 문서를 정리합니다.')
        draft['items'][0]['pricing'].update(state='paid', amount='2000')
        draft['items'][0]['valuation'].update(mode='manual', boundaries=['500', '1000', '2000'])
        draft['panel'].update(sample_size=1, tags=[canonical_tag_id('skill:文書作成')])
        draft = self.app.save(draft['id'], draft)
        self.app.start(draft['id'])
        self.app.workers[draft['id']][0].join(3)
        self.assertFalse(self.app.status(draft['id'])['active'])
        directory = self.app.directory(draft['id'])
        manifest = (directory/'run.json').read_bytes()
        with sqlite3.connect(directory/'run.sqlite') as db:
            fingerprint = db.execute('SELECT fingerprint FROM run').fetchone()[0]
        preferences = self.app.home/'ui-preferences.json'
        atomic_json(preferences, {'tag_locale': 'en', 'sidebar_width': 245})
        before = preferences.read_bytes()
        response = self.app.responses(draft['id'])
        report = self.app.report(draft['id'])
        for context in (response['report_context'], response['context'], report['report_context'],
                        report['responses']['report_context'], report['responses']['context']):
            self.assertEqual(context['tag_locale'], 'ko')
            self.assertEqual(context['panel']['tags'], draft['panel']['tags'])
        tag = draft['panel']['tags'][0]
        body, _ = self.app.export(draft['id'], 'md')
        self.assertIn('#' + report['report_context']['tag_labels'][tag]['ko'], body)
        self.assertNotIn('#' + report['report_context']['tag_labels'][tag]['en'], body)
        self.assertEqual(preferences.read_bytes(), before)
        self.assertEqual((directory/'run.json').read_bytes(), manifest)
        with sqlite3.connect(directory/'run.sqlite') as db:
            self.assertEqual(db.execute('SELECT fingerprint FROM run').fetchone()[0], fingerprint)

    def test_frozen_experiment_uses_its_source_and_base_filters(self):
        draft = self.app.create()
        spec = copy.deepcopy(self.app.make_spec(draft, allow_empty=True))
        spec['panel'] = self.panel(tags=['skill:python'], tag_mode='all', selected_uuids=['authored-person-000'])
        frozen = {key: value for key, value in draft.items() if key not in {'run', 'legacy_items', 'question_catalog'}}
        frozen['panel'] = copy.deepcopy(spec['panel'])
        atomic_json(self.app.directory(draft['id'])/'run.json', {'draft': frozen, 'spec': spec, 'source': self.app.source})
        self.app.source = self.write_pack(8, 'authored-v2')
        self.app.data_path, self.app.people = self.app.source_pack(self.app.source)
        self.assertEqual(self.app.panel_tags(self.panel(), query='文書作成')['tags'][0]['count'], 8)
        frozen_result = self.app.panel_tags(self.panel(prefecture='大阪府'), draft['id'], query='文書作成')
        self.assertEqual(frozen_result['tags'][0]['count'], 20)

    def test_validation_precedes_filter_removal_and_http_rejects_malformed_inputs(self):
        invalid = [self.panel(tags='skill:python'), self.panel(tags=['skill:Python']),
                   self.panel(tags=['skill:python', 'skill:python']), self.panel(tag_mode='bad'),
                   self.panel(sample_size=0), self.panel(selected_uuids=[]),
                   self.panel(prefecture=['東京都']), self.panel(unknown_field='ignored')]
        with patch('persona_lab.tags.tag_catalog', side_effect=AssertionError('validation skipped')):
            for panel in invalid:
                with self.subTest(panel=panel), self.assertRaises(ContractError):
                    self.app.panel_tags(panel)
            for query in (None, [], 'x'*121):
                with self.subTest(query=query), self.assertRaises(ContractError):
                    self.app.panel_tags(self.panel(), query=query)
            for locale in (None, [], 'fr', 'KO'):
                with self.subTest(locale=locale), self.assertRaises(ContractError):
                    self.app.panel_tags(self.panel(), locale=locale)
        server = make_server(self.app)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        base = f'http://127.0.0.1:{server.server_address[1]}'
        def call(body):
            request = urllib.request.Request(base+'/api/panel/tags', data=json.dumps(body).encode(),
                headers={'X-Persona-Token': server.token, 'Content-Type': 'application/json'})
            return urllib.request.urlopen(request, timeout=5)
        try:
            with call({'panel': self.panel(), 'query': '＃ＰＹＴＨＯＮ', 'locale': 'en'}) as response:
                result = json.load(response)
                self.assertEqual(result['tags'][0]['id'], canonical_tag_id('skill:python'))
                self.assertEqual(result['tag_locale'], 'en')
            with self.assertRaises(urllib.error.HTTPError) as caught:
                call({'panel': invalid[0]})
            self.assertEqual(caught.exception.code, 400)
            with self.assertRaises(urllib.error.HTTPError) as caught:
                call({'panel': self.panel(), 'locale': 'fr'})
            self.assertEqual(caught.exception.code, 400)
        finally:
            server.shutdown(); server.server_close(); thread.join(2)


if __name__ == '__main__':
    unittest.main()
