import copy
import hashlib
import io
import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    import pyarrow as pa
    import pyarrow.parquet as pq
except ImportError:
    pa = pq = None

from persona_lab.adapter import read_personas
from persona_lab.catalog import indexed_page
from persona_lab.contracts import ContractError
from persona_lab.parquet_import import create_import, run_import, read_import_status, _download, _license_check, DATASET, REVISION

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(pa is not None, 'optional PyArrow requires .venv-data')
class ParquetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); (self.root / 'data/packs').mkdir(parents=True)
        self.source = json.loads((ROOT / 'data/packs/synthetic-fixture.json').read_text())
        self.source.update(source_id='persona-lab/parquet-synthetic-tests', version='parquet-test-v1')
        self.path = self.root / 'input.parquet'
        self.rows = [{'uuid': f'explicit-synthetic-{i:04}', 'persona': '明示的な合成人物 needle_%' if i % 9 == 0 else '明示的な合成人物', 'professional_persona': '合成職業', 'sports_persona': None if i % 3 == 0 else '散歩', 'arts_persona': '', 'culinary_persona': '料理', 'age': 20 + i % 50, 'prefecture': '東京都' if i % 2 == 0 else '大阪府', 'skills_and_expertise_list': '["fixture_only"]', 'fixture_extra': f'preserved-{i}'} for i in range(130)]
        self.write(self.rows)

    def write(self, rows): pq.write_table(pa.Table.from_pylist(rows), self.path, row_group_size=41)
    def create(self, batch_size=16): return create_import(self.root, local_path=self.path, source=self.source, batch_size=batch_size)
    def manifest(self, status): return json.loads((self.root / 'data/packs' / (status['pack_id'] + '.json')).read_text())

    def test_cancel_resume_matches_uninterrupted_and_preserves_originals_and_views(self):
        identifier = self.create(); event = threading.Event()
        paused = run_import(self.root, identifier, cancelled=event.is_set, progress=lambda status: event.set() if status['rows'] >= 32 else None)
        self.assertEqual((paused['status'], paused['rows'], paused['row_group'], paused['row_offset']), ('paused', 32, 0, 32))
        done = run_import(self.root, identifier); source = self.manifest(done)
        people = list(read_personas(self.root / 'data/packs' / source['data_file'], source))
        self.assertEqual([person.raw for person in people], self.rows)
        self.assertEqual(len(people), 130); self.assertEqual(len(people[0].narratives), 6)
        self.assertEqual(people[0].missing['travel_persona'], 'absent')
        self.assertEqual(people[0].missing['sports_persona'], 'null')
        self.assertEqual(people[0].missing['arts_persona'], 'empty')
        self.assertEqual(source['license_id'], 'LicenseRef-Project-Fixture')
        self.assertIn('parquet-sha256:', source['version'])
        self.assertNotIn('purchase_propensity', people[0].raw)
        baseline = self.root / 'baseline'; (baseline / 'data/packs').mkdir(parents=True)
        baseline_id = create_import(baseline, local_path=self.path, source=self.source, batch_size=16)
        other = run_import(baseline, baseline_id); other_manifest = json.loads((baseline / 'data/packs' / (other['pack_id'] + '.json')).read_text())
        self.assertEqual(source['local_sha256'], other_manifest['local_sha256'])

    def test_indexed_filter_is_for_whole_panel_and_literal_query_not_twenty_row_cap(self):
        done = run_import(self.root, self.create()); source = self.manifest(done); path = self.root / 'data/packs' / source['data_file']
        people, count = indexed_page(self.root, source, path, {'selection': 'all'}, 120)
        self.assertEqual((count, len(people)), (130, 10)); self.assertEqual(people[0].uuid, self.rows[120]['uuid'])
        people, count = indexed_page(self.root, source, path, {'selection': 'filter', 'query': 'needle_%', 'age_min': 40}, 0)
        expected = [row for row in self.rows if 'needle_%' in row['persona'] and row['age'] >= 40]
        self.assertEqual(count, len(expected)); self.assertEqual([person.uuid for person in people], [row['uuid'] for row in expected])

    def test_duplicate_uuid_rejects_current_batch_and_no_pack_is_published(self):
        rows = copy.deepcopy(self.rows); rows[65]['uuid'] = rows[2]['uuid']; self.write(rows)
        identifier = self.create()
        with self.assertRaisesRegex(ContractError, 'duplicate original UUID'): run_import(self.root, identifier)
        state = read_import_status(self.root, identifier)
        self.assertEqual(state['status'], 'failed'); self.assertEqual(state['rows'], 57)
        self.assertEqual(list((self.root / 'data/packs').glob('*.json')), [])
        with sqlite3.connect(self.root / 'imports' / identifier / 'checkpoint.sqlite') as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM people').fetchone()[0], 57)

    def test_crash_after_output_before_sql_commit_truncates_tail_and_resumes(self):
        import persona_lab.parquet_import as module
        original = module._commit; failed = False
        def injected(db, state):
            nonlocal failed
            if state['rows'] == 32 and state['status'] == 'running' and not failed:
                failed = True; raise RuntimeError('simulated post-write crash')
            return original(db, state)
        identifier = self.create()
        with patch.object(module, '_commit', side_effect=injected), self.assertRaisesRegex(RuntimeError, 'post-write'):
            run_import(self.root, identifier)
        state = read_import_status(self.root, identifier)
        self.assertEqual(state['rows'], 16)
        output = self.root / 'imports' / identifier / 'records.jsonl'
        self.assertGreater(output.stat().st_size, state['output_bytes'])
        done = run_import(self.root, identifier); source = self.manifest(done)
        self.assertEqual([person.raw for person in read_personas(self.root / 'data/packs' / source['data_file'], source)], self.rows)

    def test_changed_input_and_changed_output_prefix_reject_resume(self):
        identifier = self.create(); state = run_import(self.root, identifier, max_batches=1)
        with self.path.open('ab') as stream: stream.write(b'changed')
        with self.assertRaisesRegex(ContractError, 'local source changed'): run_import(self.root, identifier)
        self.write(self.rows)
        output = self.root / 'imports' / identifier / 'records.jsonl'
        with output.open('r+b') as stream: stream.write(b'!')
        with self.assertRaisesRegex(ContractError, 'output prefix changed'): run_import(self.root, identifier)

    def test_import_manifest_change_rejects_resume_and_completed_pack_is_immutable(self):
        identifier = self.create(); run_import(self.root, identifier, max_batches=1)
        manifest = self.root / 'imports' / identifier / 'manifest.json'; original = manifest.read_text()
        spec = json.loads(original); spec['batch_size'] = 32; manifest.write_text(json.dumps(spec))
        with self.assertRaisesRegex(ContractError, 'spec changed'): run_import(self.root, identifier)
        manifest.write_text(original); done = run_import(self.root, identifier)
        self.assertEqual(run_import(self.root, identifier)['pack_id'], done['pack_id'])
        published = self.root / 'data/packs' / self.manifest(done)['data_file']
        with published.open('r+b') as stream: stream.write(b'!')
        with self.assertRaisesRegex(ContractError, 'published pack changed'): run_import(self.root, identifier)

    def test_local_input_requires_explicit_source_and_official_basename_is_restricted(self):
        with self.assertRaises(ContractError): create_import(self.root, local_path=self.path, source=None)
        with self.assertRaises(ContractError): create_import(self.root, shard='../../outside.parquet')

    def test_download_range_ignored_and_prefix_changed_never_append_wrong_bytes(self):
        directory = self.root / 'download'; directory.mkdir()
        part = directory / 'source.parquet.part'; part.write_bytes(b'abcd')
        state = {'license_checked_at': 'verified-for-test', 'download_bytes': 4, 'download_sha256': hashlib.sha256(b'abcd').hexdigest()}
        spec = {'item': {'filename': 'train-00000-of-00008.parquet', 'bytes': 12, 'sha256': hashlib.sha256(b'abcdefghijkl').hexdigest()}}
        response = io.BytesIO(b'abcdefghijkl'); response.status = 200; response.headers = {}; response.geturl = lambda: 'https://huggingface.co/test'
        with sqlite3.connect(directory / 'test.sqlite') as db, patch('persona_lab.parquet_import.urllib.request.urlopen', return_value=response):
            with self.assertRaisesRegex(ContractError, 'safe range resume'): _download(directory, spec, db, state, lambda: False, lambda _: None)
        self.assertEqual(part.read_bytes(), b'abcd')
        part.write_bytes(b'abce')
        with sqlite3.connect(directory / 'test.sqlite') as db, patch('persona_lab.parquet_import.urllib.request.urlopen') as network:
            with self.assertRaisesRegex(ContractError, 'download prefix changed'): _download(directory, spec, db, state, lambda: False, lambda _: None)
            network.assert_not_called()

    def test_official_license_and_revision_must_match_pinned_metadata(self):
        valid = {'id': DATASET, 'sha': REVISION, 'cardData': {'license': 'cc-by-4.0'}}
        for key, value, expected in (('sha', 'changed', 'metadata mismatch'), ('cardData', {'license': 'changed'}, 'license changed')):
            metadata = {**valid, key: value}
            with patch('persona_lab.parquet_import.urllib.request.urlopen', return_value=io.BytesIO(json.dumps(metadata).encode())):
                with self.assertRaisesRegex(ContractError, expected): _license_check()


if __name__ == '__main__': unittest.main()
