"""Small authored packs exercise cohort freezing and questionnaire plumbing."""
import copy
import hashlib
import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from persona_desktop.application import Application, atomic_json
from persona_lab.backends import FixtureBackend
from persona_lab.responses import SURVEY_SCENARIO_ID, SURVEY_V3_SCENARIO_ID
from persona_lab.runner import matches, run, selected_personas
from persona_lab.survey import PREDECESSOR_DOMAINS, SURVEY_DOMAINS


ROOT = Path(__file__).resolve().parents[1]
DOCUMENT = '# 메모 도구\n\n## 주요 기능\n태그와 검색으로 문서를 정리합니다.\n'


class SamplingFlowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / 'resources'
        self.home = Path(temporary.name) / 'home'
        (self.root / 'assets/data').mkdir(parents=True)
        (self.root / 'assets/questions.json').write_bytes((ROOT / 'assets/questions.json').read_bytes())
        self.write_pack(20, 'authored-v1')
        self.app = Application(self.root, self.home, FixtureBackend())
        self.addCleanup(lambda: self.app.close())

    def write_pack(self, count, version):
        rows = [{'uuid': f'authored-person-{index:03d}', 'age': 20 + index,
                 'sex': ('女性', '男性', 'nonbinary', None)[index % 4],
                 'prefecture': '東京都' if index % 2 == 0 else '大阪府',
                 'persona': '작가로서 매일 문서를 정리한다.' if index % 2 == 0 else '개발자로서 매일 코드를 작성한다.'}
                for index in range(count)]
        data = ''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows).encode()
        source = {'schema_version': '0.1', 'source_id': 'persona-lab/sampling-test',
                  'version': version, 'url': 'local:project-authored',
                  'license_id': 'LicenseRef-Project-Fixture', 'license_url': 'local:test',
                  'origin': 'project_synthetic_fixture', 'record_count': count,
                  'data_file': f'{version}.jsonl', 'local_sha256': hashlib.sha256(data).hexdigest()}
        (self.root / 'assets/data' / source['data_file']).write_bytes(data)
        atomic_json(self.root / 'assets/data/nemotron-japan-sample.json', source)
        return source

    def configure(self, draft, count=3, items=2, repeats=2):
        candidate = copy.deepcopy(draft)
        candidate['items'] = [{'id': f'{index + 1:032x}', 'name': f'메모 {index + 1}',
                               'document': DOCUMENT, 'pricing': {'state': 'paid', 'amount': '2000',
                                                               'currency': 'JPY', 'billing': 'one_time'}}
                              for index in range(items)]
        candidate['panel'].update(sample_size=count, sex='female', age_min=24, age_max=36,
                                  prefecture='東京都', query='작가')
        candidate['settings']['repeats'] = repeats
        return self.app.save(draft['id'], candidate)

    def finish(self, identifier):
        self.app.workers[identifier][0].join(5)
        status = self.app.status(identifier)
        self.assertFalse(status['active'], status)
        return status

    def test_filtered_hash_sample_is_order_independent_and_frozen(self):
        panel = {'selection': 'random', 'sample_size': 2, 'sample_seed': 17,
                 'sampling_version': 'hash-rank-v1', 'sex': 'female',
                 'age_min': 24, 'age_max': 36, 'prefecture': '東京都', 'query': '작가'}
        people = self.app.people
        eligible = [person for person in people if matches(person, panel)]
        self.assertEqual([person.raw['age'] for person in eligible], [24, 28, 32, 36])
        sampled = [person.uuid for person in selected_personas(people, panel)]
        self.assertEqual(sampled, [person.uuid for person in selected_personas(reversed(people), panel)])
        alternatives = [[person.uuid for person in selected_personas(people, {**panel, 'sample_seed': seed})]
                        for seed in range(18, 24)]
        self.assertTrue(any(draw != sampled for draw in alternatives))
        self.assertEqual(len(list(selected_personas(people, {**panel, 'sample_size': 100}))), 4)
        frozen = {**panel, 'sample_seed': 999, 'selected_uuids': sampled[::-1]}
        self.assertEqual([person.uuid for person in selected_personas(reversed(people), frozen)], sampled[::-1])
        for sex, index in [('female', 0), ('male', 1), ('other', 2), ('unknown', 3)]:
            self.assertTrue(matches(people[index], {'selection': 'filter', 'sex': sex}))
        self.assertFalse(matches(eligible[0], {**panel, 'query': '존재하지 않는 직업'}))
        self.assertFalse(matches(eligible[0], {**panel, 'age_min': 25}))

    def test_random_defaults_and_frozen_eight_stage_cohort_link_on_resume(self):
        draft = self.app.create()
        self.assertEqual(draft['workflow'], SURVEY_V3_SCENARIO_ID)
        self.assertEqual((draft['panel']['selection'], draft['panel']['sample_size']), ('random', 100))
        self.assertIs(type(draft['panel']['sample_seed']), int)
        preview = self.app.panel(draft['panel'])
        self.assertEqual((preview['count'], preview['eligible_count'], preview['requested_size']), (20, 20, 100))
        self.assertNotIn('items', preview)
        draft = self.configure(draft)
        preview = self.app.panel(draft['panel'])
        self.assertEqual((preview['count'], preview['eligible_count'], preview['requested_size']), (3, 4, 3))
        self.assertNotIn('items', preview)
        self.assertNotIn('selected_uuids', draft['panel'])
        # The original eight-stage contract remains linked after the default changes.
        draft['workflow'] = SURVEY_SCENARIO_ID
        spec = self.app.make_spec(draft)
        selected = [person.uuid for person in selected_personas(self.app.people, spec['panel'])]
        spec['panel'] = {**spec['panel'], 'selected_uuids': selected}
        draft['panel'] = spec['panel']
        atomic_json(self.app.directory(draft['id']) / 'run.json', {
            'draft': {key: value for key, value in draft.items() if key not in {'run', 'legacy_items', 'question_catalog'}},
            'spec': spec, 'source': self.app.source, 'created_at': 'test-frozen-time'})
        entered, release = threading.Event(), threading.Event()
        observed = []

        class PauseOnce(FixtureBackend):
            def decide(inner, job):
                observed.append(job)
                if job.ordinal == 2 and not entered.is_set():
                    entered.set()
                    if not release.wait(5):
                        raise ValueError('test did not release its fixture backend')
                return super().decide(job)

        self.app.test_backend = PauseOnce()
        try:
            self.app.start(draft['id'])
            self.assertTrue(entered.wait(3))
            self.app.cancel(draft['id'])
        finally:
            release.set()
        paused = self.finish(draft['id'])
        self.assertEqual((paused['status'], paused['cursor'], paused['total']), ('paused', 3, 96))
        snapshot = self.app.snapshot(draft['id'])
        selected = snapshot['spec']['panel']['selected_uuids']
        self.assertEqual(len(selected), 3)
        self.assertEqual(snapshot['draft']['panel']['selected_uuids'], selected)
        self.assertEqual(tuple(question['domain'] for question in snapshot['spec']['questions']), SURVEY_DOMAINS)
        store = self.app.directory(draft['id']) / 'run.sqlite'
        with sqlite3.connect(store) as db:
            preserved = db.execute('SELECT payload FROM results ORDER BY ordinal').fetchall()
        self.app.start(draft['id'])
        completed = self.finish(draft['id'])
        self.assertEqual((completed['status'], completed['cursor'], completed['backend_errors']), ('completed', 96, 0))
        self.assertEqual(self.app.snapshot(draft['id']), snapshot)
        with sqlite3.connect(store) as db:
            payloads = db.execute('SELECT payload FROM results ORDER BY ordinal').fetchall()
        self.assertEqual(payloads[:3], preserved)
        records = [json.loads(payload) for (payload,) in payloads]
        self.assertEqual({record['uuid'] for record in records}, set(selected))
        by_id = {record['job_id']: record for record in records}
        final = [record for record in records if record['domain'] == 'purchase']
        self.assertEqual(len(final), 12)
        for record in final:
            self.assertEqual(set(record['assessments']), set(PREDECESSOR_DOMAINS))
            for domain, prior in record['assessments'].items():
                earlier = by_id[prior['job_id']]
                self.assertEqual(earlier['domain'], domain)
                for key in ('persona_id', 'product_id', 'repeat'):
                    self.assertEqual(earlier[key], record[key])
        self.assertEqual(len(observed), 96)
        for repeat in (0, 1):
            report = self.app.responses(draft['id'], repeat)
            self.assertEqual(report['count'], 3)
            self.assertEqual([person['uuid'] for person in report['people']], selected)
            for person in report['people']:
                self.assertEqual(len(person['items']), 2)
                for item in person['items']:
                    self.assertTrue(set(SURVEY_DOMAINS) <= set(item))
                    self.assertTrue(all(item[domain]['job_id'] in by_id for domain in SURVEY_DOMAINS))

    def test_frozen_eight_stage_run_resumes_from_its_source_after_pool_expands(self):
        self.app.close()
        old_source = self.write_pack(4, 'authored-old-v1')
        self.app = Application(self.root, self.home, FixtureBackend())
        draft = self.app.create()
        draft['workflow'] = SURVEY_SCENARIO_ID
        draft['panel'] = {'selection': 'all'}
        draft['settings']['repeats'] = 1
        draft['items'][0].update(name='메모', document=DOCUMENT,
                                 pricing={'state': 'paid', 'amount': '2000', 'currency': 'JPY', 'billing': 'one_time'})
        spec = self.app.make_spec(draft)
        self.assertEqual(len(spec['questions']), 8)
        directory = self.app.directory(draft['id'])
        snapshot = {'draft': {key: value for key, value in draft.items() if key not in {'run', 'legacy_items'}},
                    'spec': spec, 'source': old_source, 'created_at': 'test-frozen-time'}
        atomic_json(directory / 'run.json', snapshot)
        store = directory / 'run.sqlite'
        partial = run(self.app.data_path, old_source, spec, store, FixtureBackend(), max_batches=2)
        self.assertEqual((partial['cursor'], partial['total']), (2, 32))
        with sqlite3.connect(store) as db:
            fingerprint = db.execute('SELECT fingerprint FROM run').fetchone()[0]
            preserved = db.execute('SELECT payload FROM results ORDER BY ordinal').fetchall()
        manifest = (directory / 'run.json').read_bytes()
        self.app.close()
        self.write_pack(20, 'authored-expanded-v2')
        self.app = Application(self.root, self.home, FixtureBackend())
        self.assertEqual(len(self.app.people), 20)
        self.assertNotEqual(self.app.source['version'], old_source['version'])
        self.app.start(draft['id'])
        completed = self.finish(draft['id'])
        self.assertEqual((completed['status'], completed['cursor'], completed['total'], completed['backend_errors']),
                         ('completed', 32, 32, 0))
        self.assertEqual((directory / 'run.json').read_bytes(), manifest)
        with sqlite3.connect(store) as db:
            self.assertEqual(db.execute('SELECT fingerprint FROM run').fetchone()[0], fingerprint)
            payloads = db.execute('SELECT payload FROM results ORDER BY ordinal').fetchall()
        self.assertEqual(payloads[:2], preserved)
        self.assertEqual({json.loads(payload)['source_version'] for (payload,) in payloads}, {old_source['version']})
        report = self.app.responses(draft['id'])
        self.assertEqual(report['count'], 4)
        detail = self.app.detail(draft['id'], json.loads(payloads[0][0])['job_id'])
        self.assertEqual(detail['record']['source_version'], old_source['version'])


if __name__ == '__main__':
    unittest.main()
