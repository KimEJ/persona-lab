import copy
import io
import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from persona_lab.backends import FixtureBackend, JuliaBackend
from persona_lab.contracts import ContractError, Decision
from persona_lab.runner import run, jobs, read_status
from persona_lab.reports import summarize

ROOT = Path(__file__).resolve().parents[1]


class KeyedBatch(FixtureBackend):
    batch_limit = 3
    def decide_batch(self, batch):
        return {job.job_id: super(KeyedBatch, self).decide(job) for job in reversed(batch)}


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = ROOT / 'data/packs/synthetic-fixture.jsonl'
        self.source = json.loads((ROOT / 'data/packs/synthetic-fixture.json').read_text())
        self.spec = json.loads((ROOT / 'examples/experiment.json').read_text())
        self.store = Path(self.temp.name) / 'batch.sqlite'

    def execute(self, backend, **kwargs):
        return run(self.path, self.source, self.spec, self.store, backend, **kwargs)

    def rows(self, store=None):
        with sqlite3.connect(store or self.store) as db:
            return db.execute('SELECT ordinal,job_id,payload FROM results ORDER BY ordinal').fetchall()

    def test_reordered_batch_ids_and_resume_equal_single_item_baseline(self):
        self.assertEqual(self.execute(KeyedBatch(), max_batches=1)['cursor'], 8)
        self.assertEqual(self.execute(KeyedBatch())['cursor'], 56)
        baseline = Path(self.temp.name) / 'baseline.sqlite'
        run(self.path, self.source, self.spec, baseline, FixtureBackend())
        self.assertEqual(self.rows(), self.rows(baseline))

    def test_cancel_in_flight_commits_whole_returned_chunk_then_resumes(self):
        event = threading.Event()
        class Cancel(KeyedBatch):
            def decide_batch(inner, batch):
                answer = super().decide_batch(batch); event.set(); return answer
        self.assertEqual(self.execute(Cancel(), cancelled=event.is_set)['cursor'], 3)
        saved = self.rows()
        self.assertEqual(self.execute(KeyedBatch())['cursor'], 56)
        self.assertEqual(self.rows()[:3], saved)

    def test_one_bad_item_and_transport_timeout_do_not_discard_neighbors_and_retry_only_errors(self):
        class Faults(KeyedBatch):
            def decide_batch(inner, batch):
                if batch[0].ordinal == 8: raise TimeoutError('batch timeout')
                answers = super().decide_batch(batch)
                for job in batch:
                    if job.ordinal == 1: answers[job.job_id] = ContractError('bad item')
                return answers
        status = self.execute(Faults())
        self.assertEqual((status['cursor'], status['backend_errors']), (56, 4))
        saved = {row[1]: row[2] for row in self.rows() if not json.loads(row[2])['backend_error']}
        called = []
        class Retry(KeyedBatch):
            def decide_batch(inner, batch):
                called.extend(job.ordinal for job in batch); return super().decide_batch(batch)
        self.assertEqual(self.execute(Retry(), retry_errors=True)['backend_errors'], 0)
        self.assertEqual(called, [1, 8, 9, 10])
        current = {row[1]: row[2] for row in self.rows()}
        self.assertTrue(all(current[key] == payload for key, payload in saved.items()))

    def test_missing_batch_id_is_a_batch_error_without_guessing_alignment(self):
        class Missing(KeyedBatch):
            def decide_batch(inner, batch):
                answers = super().decide_batch(batch); answers.pop(batch[0].job_id); return answers
        self.assertEqual(self.execute(Missing())['backend_errors'], 56)
        self.assertEqual(summarize(self.store)['valid_decisions'], 0)

    def test_unexpected_failure_rolls_back_current_commit_batch(self):
        class Fatal(KeyedBatch):
            def decide_batch(inner, batch):
                if batch[0].ordinal == 11: raise RuntimeError('fatal test')
                return super().decide_batch(batch)
        with self.assertRaisesRegex(RuntimeError, 'fatal test'): self.execute(Fatal())
        self.assertEqual(read_status(self.store)['cursor'], 8)
        self.assertEqual(len(self.rows()), 8)
        self.assertEqual(self.execute(KeyedBatch())['cursor'], 56)

    def test_julia_transport_preserves_ids_and_item_errors_and_gates_unsupported_price(self):
        self.spec['assumptions'] = {'purchase_budget_jpy_minor': 1500}
        batch = list(jobs(self.path, self.source, self.spec))[:3]
        def reply(request, **kwargs):
            rows = json.loads(request.data)['rows']
            self.assertEqual([row['id'] for row in rows], [job.job_id for job in batch])
            return io.BytesIO(json.dumps({'results': [
                {'id': rows[2]['id'], 'index': 3},
                {'id': rows[1]['id'], 'error': 'strict encoding rejected', 'type': 'ValueError'},
                {'id': rows[0]['id'], 'index': 1},
            ]}).encode())
        backend = JuliaBackend()
        with patch('persona_lab.backends.urllib.request.urlopen', side_effect=reply):
            outcomes = backend.decide_batch(batch)
        self.assertEqual(outcomes[batch[0].job_id].choice, 'later')
        self.assertIsInstance(outcomes[batch[1].job_id], ContractError)
        self.assertEqual(outcomes[batch[2].job_id].choice, 'unknown')
        self.spec['products'][0]['price']['currency'] = 'USD'
        purchase = next(job for job in jobs(self.path, self.source, self.spec) if job.question['domain'] == 'purchase')
        with patch('persona_lab.backends.urllib.request.urlopen') as network:
            self.assertEqual(backend.decide(purchase).choice, 'unknown'); network.assert_not_called()


if __name__ == '__main__': unittest.main()
