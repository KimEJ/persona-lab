"""Explicit source tags narrow cohorts without changing frozen sample behavior."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from persona_lab.contracts import ContractError, Persona, validate_experiment
from persona_lab.runner import matches, selected_personas
from persona_lab.tags import (REGISTRY_PATH, _registry, canonical_tag_id, matching_tags,
                              persona_tags, source_tag_id, source_tags, tag_catalog,
                              tag_metadata, tag_source_labels, valid_tag_id)


def person(identifier, **fields):
    raw = {'uuid': identifier, **fields}
    return Persona(f'person-{identifier}', identifier, {}, raw, 'content-hash', {}, {}, {})


def experiment(panel):
    return {
        'schema_version': '0.1', 'experiment_id': 'tag-panel-test',
        'mode': 'independent_comparison', 'panel': copy.deepcopy(panel),
        'seed': 7, 'repeats': 1, 'batch_size': 4, 'assumptions': {},
        'scenario': {'initial_state_id': 'initial-v1', 'events': []},
        'products': [{'id': 'memo', 'name': '메모', 'intro': '메모를 정리합니다.',
                      'features': [], 'price': {'amount_minor': 1000,
                                              'currency': 'JPY', 'billing': 'one_time'}}],
        'questions': [{'id': 'need', 'domain': 'need', 'prompt': '필요한가요?',
                       'choices': ['now', 'none', 'unknown']}],
    }


class IsolatedRegistryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.registry_path = Path(temporary.name) / 'registry.json'
        patcher = patch('persona_lab.tags.REGISTRY_PATH', self.registry_path)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(_registry.cache_clear)
        self.write_registry([])

    def write_registry(self, entries):
        self.registry_path.write_text(json.dumps({'version': 1, 'tags': entries}), encoding='utf-8')
        _registry.cache_clear()


def calligraphy_entry():
    return {'id': 'interest:concept/calligraphy', 'kind': 'interest', 'source': ['書道'],
            'labels': {'ko': '서예', 'en': 'Calligraphy', 'ja': '書道'}}


class SourceTagTests(IsolatedRegistryTests):
    def test_python_and_json_lists_normalize_labels_and_deduplicate(self):
        tags = source_tags({
            'skills_and_expertise_list': "[' Ｐｙｔｈｏｎ ', 'Python', 'Data\\t Science']",
            'hobbies_and_interests_list': json.dumps([' Ｊａｚｚ ', 'jazz'], ensure_ascii=False),
            'occupation': '  Software\n  Engineer  ',
        })
        self.assertEqual(set(tags), {'skill:python', 'skill:data science',
                                    'interest:jazz', 'occupation:software engineer'})
        self.assertEqual(tags['skill:data science'], 'Data Science')
        self.assertEqual(tags['occupation:software engineer'], 'Software Engineer')
        self.assertTrue(all(valid_tag_id(identifier) for identifier in tags))

    def test_only_explicit_lists_and_occupation_create_tags(self):
        self.assertEqual(source_tags({
            'persona': 'Python expert who enjoys Jazz.',
            'professional_persona': 'Software Engineer',
            'skills_and_expertise': 'Python, SQL',
            'hobbies_and_interests': 'Jazz, hiking',
        }), {})
        malformed = ('not a list', "['Python'", "{'Python': 1}", "('Python',)",
                     "'Python'", 'null', '123')
        for serialized in malformed:
            with self.subTest(serialized=serialized):
                self.assertEqual(source_tags({'skills_and_expertise_list': serialized}), {})
        for value in (None, 17, False, {'name': 'Engineer'}):
            with self.subTest(occupation=value):
                self.assertEqual(source_tags({'occupation': value}), {})

    def test_blank_and_non_string_list_members_are_excluded(self):
        tags = source_tags({
            'skills_and_expertise_list': "['Python', '', '   ', None, 7, True, ['SQL'], {'x': 'R'}]",
            'hobbies_and_interests_list': '["Jazz", null, false, 3, "  "]',
        })
        self.assertEqual(tags, {'skill:python': 'Python', 'interest:jazz': 'Jazz'})

    def test_serialized_code_cannot_execute(self):
        payloads = (
            "__import__('os').system('tag-test-must-not-execute')",
            "[__import__('os').system('tag-test-must-not-execute')]",
            "[value for value in ['Python']]",
        )
        with patch('os.system') as system, patch('builtins.eval') as unsafe_eval:
            for payload in payloads:
                with self.subTest(payload=payload):
                    self.assertEqual(source_tags({'skills_and_expertise_list': payload}), {})
            system.assert_not_called()
            unsafe_eval.assert_not_called()

    def test_label_and_identifier_lengths_are_bounded(self):
        tags = source_tags({'skills_and_expertise_list': repr(['x' * 200, 'z' * 300]),
                             'occupation': 'Y' * 200})
        self.assertEqual(len(tags), 2)
        self.assertTrue(all(len(label) <= 200 for label in tags.values()))
        self.assertTrue(all(len(identifier) <= 256 and valid_tag_id(identifier)
                            for identifier in tags))
        self.assertNotIn('skill:' + 'z' * 300, tags)

    def test_catalog_counts_people_once_and_sorts_by_count_then_id(self):
        people = [
            person('one', skills_and_expertise_list="['Python', 'python', 'SQL']",
                   hobbies_and_interests_list="['Python', 'Jazz']", occupation='Engineer'),
            person('two', skills_and_expertise_list='["Python"]', occupation='Engineer'),
            person('three', hobbies_and_interests_list="['Jazz']"),
        ]
        catalog = tag_catalog(iter(people))
        expected = [(source_tag_id(identifier), count) for identifier, count in (
            ('interest:jazz', 2), ('occupation:engineer', 2), ('skill:python', 2),
            ('interest:python', 1), ('skill:sql', 1))]
        self.assertEqual([(entry['id'], entry['count']) for entry in catalog],
                         sorted(expected, key=lambda value: (-value[1], value[0])))
        for entry in catalog:
            self.assertEqual(set(entry), {'id', 'label', 'labels', 'aliases', 'kind', 'count'})
            self.assertEqual(entry['kind'], entry['id'].split(':', 1)[0])
        self.assertEqual(tag_catalog([]), [])


class TagPanelTests(IsolatedRegistryTests):
    def setUp(self):
        super().setUp()
        self.people = [
            person('one', skills_and_expertise_list="['ＰＹＴＨＯＮ']",
                   hobbies_and_interests_list="['Jazz']", occupation='Engineer',
                   persona='매일 메모를 정리한다.', age=32, sex='女性', prefecture='東京都'),
            person('two', skills_and_expertise_list="['Python']",
                   hobbies_and_interests_list="['Hiking']", occupation='Writer',
                   persona='매일 메모를 정리한다.', age=34, sex='女性', prefecture='東京都'),
            person('three', skills_and_expertise_list="['SQL']",
                   hobbies_and_interests_list="['Jazz']", occupation='Engineer',
                   persona='매일 코드를 작성한다.', age=45, sex='男性', prefecture='大阪府'),
            person('four', skills_and_expertise_list="['Python programming']",
                   persona='Jazz를 듣고 메모를 정리한다.', age=28, sex='女性', prefecture='東京都'),
        ]

    def selected(self, panel, people=None):
        return [entry.uuid for entry in selected_personas(self.people if people is None else people, panel)]

    def test_exact_ids_match_normalized_source_labels(self):
        panel = {'selection': 'filter', 'tags': ['skill:python']}
        self.assertEqual(self.selected(panel), ['one', 'two'])
        self.assertFalse(matches(self.people[3], panel))
        self.assertFalse(matches(self.people[3], {'selection': 'filter', 'tags': ['interest:jazz']}))

    def test_any_all_and_existing_filters_are_combined(self):
        panel = {'selection': 'filter', 'tags': ['skill:python', 'interest:jazz']}
        self.assertEqual(self.selected(panel), ['one', 'two', 'three'])
        self.assertEqual(self.selected({**panel, 'tag_mode': 'all'}), ['one'])
        narrowed = {**panel, 'query': '메모', 'sex': 'female',
                    'prefecture': '東京都', 'age_min': 30, 'age_max': 33}
        self.assertEqual(self.selected(narrowed), ['one'])
        self.assertEqual(self.selected({**narrowed, 'query': '존재하지 않음'}), [])
        self.assertEqual(self.selected({**narrowed, 'age_min': 33}), [])

    def test_empty_tags_preserve_query_and_demographic_filtering(self):
        panel = {'selection': 'filter', 'query': '메모', 'sex': 'female'}
        expected = self.selected(panel)
        for mode in ('any', 'all'):
            with self.subTest(mode=mode):
                self.assertEqual(self.selected({**panel, 'tags': [], 'tag_mode': mode}), expected)

    def test_canonical_tag_ids_and_panel_limits_are_validated(self):
        for identifier in ('skill:python', 'interest:jazz', 'occupation:software engineer'):
            self.assertTrue(valid_tag_id(identifier))
        invalid_ids = (None, 3, False, [], {}, '', 'python', 'other:python', 'skill:',
                       'skill:Python', 'skill:ｐｙｔｈｏｎ', ' skill:python', 'skill:python ',
                       'occupation:software  engineer', 'skill:' + 'x' * 251)
        for identifier in invalid_ids:
            with self.subTest(identifier=identifier):
                self.assertFalse(valid_tag_id(identifier))
                with self.assertRaises(ContractError):
                    validate_experiment(experiment({'selection': 'filter', 'tags': [identifier]}))
        for panel in (
            {'selection': 'filter', 'tags': []},
            {'selection': 'filter', 'tags': ['skill:python']},
            {'selection': 'filter', 'tags': ['skill:python'], 'tag_mode': 'all'},
            {'selection': 'filter', 'tags': [f'skill:item {index}' for index in range(20)]},
        ):
            with self.subTest(valid_panel=panel):
                validate_experiment(experiment(panel))
        invalid_panels = (
            {'selection': 'filter', 'tags': 'skill:python'},
            {'selection': 'filter', 'tags': None},
            {'selection': 'filter', 'tags': ['skill:python', 'skill:python']},
            {'selection': 'filter', 'tags': [f'skill:item {index}' for index in range(21)]},
            {'selection': 'filter', 'tags': [], 'tag_mode': 'either'},
            {'selection': 'filter', 'tags': [], 'tag_mode': []},
            {'selection': 'all', 'tags': ['skill:python']},
        )
        for panel in invalid_panels:
            with self.subTest(invalid_panel=panel), self.assertRaises(ContractError):
                validate_experiment(experiment(panel))

    def test_random_order_independence_and_frozen_uuid_order_are_preserved(self):
        panel = {'selection': 'random', 'sample_size': 2, 'sample_seed': 17,
                 'sampling_version': 'hash-rank-v1', 'tags': ['interest:jazz']}
        sampled = self.selected(panel)
        self.assertEqual(set(sampled), {'one', 'three'})
        self.assertEqual(self.selected(panel, reversed(self.people)), sampled)
        frozen = {**panel, 'sample_seed': 999, 'selected_uuids': sampled[::-1]}
        validate_experiment(experiment(frozen))
        self.assertEqual(self.selected(frozen, reversed(self.people)), sampled[::-1])
        with self.assertRaises(ContractError):
            self.selected({**frozen, 'tags': ['skill:sql']})
        legacy = {key: value for key, value in panel.items() if key != 'tags'}
        self.assertEqual(self.selected(legacy), self.selected({**legacy, 'tags': []}))


class PortableIdentityTests(IsolatedRegistryTests):
    def test_legacy_namespace_prefixed_label_keeps_exact_validation_and_matching(self):
        identifier = 'skill:source/foo'
        raw = {'skills_and_expertise_list': "['source/foo']"}
        self.assertTrue(valid_tag_id(identifier))
        validate_experiment(experiment({'selection': 'filter', 'tags': [identifier]}))
        self.assertEqual(source_tags(raw), {identifier: 'source/foo'})
        self.assertTrue(matches(person('legacy', **raw), {'selection': 'filter', 'tags': [identifier]}))
        self.assertEqual(canonical_tag_id(identifier), source_tag_id(identifier))
        self.assertEqual(tag_metadata(identifier)['label'], 'source/foo')

    def test_three_languages_share_concept_while_legacy_filters_remain_exact(self):
        self.write_registry([calligraphy_entry()])
        people = [person(locale, hobbies_and_interests_list=repr([label]))
                  for locale, label in (('ja', '書道'), ('en', 'Calligraphy'), ('ko', '서예'))]
        identifier = 'interest:concept/calligraphy'
        for current in people:
            with self.subTest(locale=current.uuid):
                self.assertEqual(set(persona_tags(current.raw)), {identifier})
                self.assertIn(identifier, matching_tags(current.raw))
        self.assertEqual([entry.uuid for entry in selected_personas(people, {
            'selection': 'filter', 'tags': [identifier]})], ['ja', 'en', 'ko'])
        legacy = {'selection': 'random', 'sample_size': 1, 'sample_seed': 17,
                  'tags': ['interest:書道'], 'selected_uuids': ['ja']}
        saved = copy.deepcopy(legacy)
        self.assertEqual([entry.uuid for entry in selected_personas(people, legacy)], ['ja'])
        self.assertEqual(legacy, saved)
        self.assertFalse(matches(people[1], {'selection': 'filter', 'tags': ['interest:書道']}))
        self.assertFalse(matches(people[0], {'selection': 'filter', 'tags': ['interest:calligraphy']}))
        catalog = tag_catalog([person('many', hobbies_and_interests_list="['書道', '서예']"), people[1]])
        self.assertEqual([(tag['id'], tag['count']) for tag in catalog], [(identifier, 2)])

    def test_locale_metadata_and_legacy_alias_display_keep_requested_identity(self):
        self.write_registry([calligraphy_entry()])
        for locale, label in (('ko', '서예'), ('en', 'Calligraphy'), ('ja', '書道')):
            for identifier in ('interest:concept/calligraphy', 'interest:書道',
                               'interest:calligraphy', 'interest:서예'):
                with self.subTest(locale=locale, identifier=identifier):
                    metadata = tag_metadata(identifier, locale)
                    self.assertEqual(metadata['id'], identifier)
                    self.assertEqual(metadata['label'], label)
                    self.assertEqual(set(metadata['labels']), {'ko', 'en', 'ja'})
                    self.assertTrue({'書道', '서예', 'Calligraphy'} <= set(metadata['aliases']))
        self.assertEqual(canonical_tag_id('interest:서예'), 'interest:concept/calligraphy')
        self.assertEqual(tag_metadata('interest:rare hobby', 'ko')['label'], 'rare hobby')

    def test_stable_hash_filter_survives_registry_mapping_added_later(self):
        raw = {'hobbies_and_interests_list': "['書道']"}
        hashed = source_tag_id('interest:書道')
        self.assertEqual(persona_tags(raw), {hashed: '書道'})
        panel = {'selection': 'random', 'sample_size': 1, 'sample_seed': 17,
                 'tags': [hashed], 'selected_uuids': ['ja']}
        validate_experiment(experiment(panel))
        people = [person('ja', **raw), person('other', hobbies_and_interests_list="['別の趣味']")]
        self.write_registry([calligraphy_entry()])
        self.assertEqual(set(persona_tags(raw)), {'interest:concept/calligraphy'})
        self.assertIn(hashed, matching_tags(raw))
        self.assertEqual([entry.uuid for entry in selected_personas(people, panel)], ['ja'])
        self.assertEqual(panel['tags'], [hashed])
        self.assertEqual(tag_metadata(hashed, 'en')['label'], 'Calligraphy')

    def test_ambiguous_translation_is_not_merged_and_explicit_source_wins(self):
        self.write_registry([
            {'id': 'interest:concept/mountain-walking', 'kind': 'interest', 'source': ['山歩き'],
             'labels': {'en': 'Hiking', 'ko': '산행', 'ja': '山歩き'}},
            {'id': 'interest:concept/hiking', 'kind': 'interest', 'source': ['ハイキング'],
             'labels': {'en': 'Hiking', 'ko': '하이킹', 'ja': 'ハイキング'}},
            {'id': 'skill:concept/reading-source', 'kind': 'skill', 'source': ['Reading'],
             'labels': {'en': 'Reading text', 'ko': '문서 읽기', 'ja': '文章を読む'}},
            {'id': 'skill:concept/reading-alias', 'kind': 'skill', 'source': ['読書'],
             'labels': {'en': 'Reading', 'ko': '독서', 'ja': '読書'}},
        ])
        self.assertEqual(set(persona_tags({'hobbies_and_interests_list': "['Hiking']"})),
                         {source_tag_id('interest:hiking')})
        self.assertEqual(set(persona_tags({'skills_and_expertise_list': "['Reading']"})),
                         {'skill:concept/reading-source'})
        raw = {'hobbies_and_interests_list': "['山歩き講座']", 'skills_and_expertise_list': "['山歩き']"}
        self.assertEqual(set(persona_tags(raw)),
                         {source_tag_id('interest:山歩き講座'), source_tag_id('skill:山歩き')})

    def test_missing_registry_preserves_unknown_source_hash_and_display_label(self):
        self.registry_path.unlink()
        _registry.cache_clear()
        raw = {'skills_and_expertise_list': "['미등록 도구']"}
        identifier = source_tag_id('skill:미등록 도구')
        self.assertTrue(identifier.isascii())
        self.assertTrue(valid_tag_id(identifier))
        self.assertEqual(persona_tags(raw), {identifier: '미등록 도구'})
        labels = tag_source_labels([person('unknown', **raw)], [identifier])
        self.assertEqual(labels, {identifier: '미등록 도구'})
        self.assertEqual(tag_metadata(identifier, 'en', source_label=labels[identifier])['label'], '미등록 도구')
        self.assertEqual(tag_catalog([person('unknown', **raw)])[0]['label'], '미등록 도구')


class PackagedRegistryTests(unittest.TestCase):
    def test_current_registry_labels_and_explicit_synonyms_preserve_legacy_cohorts(self):
        self.assertTrue(REGISTRY_PATH.is_file())
        _registry.cache_clear()
        self.addCleanup(_registry.cache_clear)
        self.assertEqual(tag_metadata('interest:concept/calligraphy', 'en')['label'], 'Calligraphy')
        self.assertEqual(tag_metadata('interest:書道', 'ko')['label'], '서예')
        identifier = 'skill:concept/project-management'
        people = [person('short', skills_and_expertise_list="['プロジェクト管理']"),
                  person('long', skills_and_expertise_list="['プロジェクトマネジメント']")]
        self.assertEqual(set(persona_tags(people[0].raw)), {identifier})
        self.assertEqual(set(persona_tags(people[1].raw)), {identifier})
        self.assertTrue(all(matches(entry, {'selection': 'filter', 'tags': [identifier]}) for entry in people))
        self.assertEqual([entry.uuid for entry in selected_personas(people, {
            'selection': 'filter', 'tags': ['skill:プロジェクト管理']})], ['short'])


if __name__ == '__main__':
    unittest.main()
