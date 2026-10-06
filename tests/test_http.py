"""HTTP end-to-end regression; no external browser or cloud API is used."""

import copy
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
try:
    import pyarrow as pa
    import pyarrow.parquet as pq
except ImportError:
    pa = pq = None


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        for directory in ("web", "examples"):
            shutil.copytree(ROOT / directory, cls.root / directory)
        (cls.root / 'data/packs').mkdir(parents=True)
        for name in ('synthetic-fixture', 'nemotron-japan-sample'):
            for suffix in ('.json', '.jsonl'):
                path = ROOT / 'data/packs' / (name + suffix)
                if path.is_file(): shutil.copy2(path, cls.root / 'data/packs' / path.name)
        shutil.copy2(ROOT / 'data/official-shards.json', cls.root / 'data/official-shards.json')
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0)); cls.port = sock.getsockname()[1]
        cls.base = f"http://127.0.0.1:{cls.port}"
        env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
        cls.process = subprocess.Popen([sys.executable, "-m", "persona_lab", "serve", "--root", str(cls.root), "--port", str(cls.port)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                urllib.request.urlopen(cls.base + "/api/packs", timeout=1).close()
                break
            except OSError:
                time.sleep(.05)
        else:
            cls.process.terminate(); cls.temp.cleanup()
            raise RuntimeError("test server did not start; loopback binding may require approval")

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate(); cls.process.wait(timeout=5); cls.temp.cleanup()

    def request(self, path, body=None, headers=None):
        actual = {"Content-Type": "application/json", "X-Persona-Lab": "demo-v1", **(headers or {})}
        request = urllib.request.Request(self.base + path, data=None if body is None else json.dumps(body).encode(), headers=actual)
        return urllib.request.urlopen(request, timeout=5)

    def json(self, path, body=None, headers=None):
        with self.request(path, body, headers) as response:
            return json.load(response)

    def complete(self, id):
        for _ in range(100):
            status = self.json("/api/runs/" + id)
            if not status["active"]:
                self.assertEqual(status["status"], "completed", status)
                return status
            time.sleep(.03)
        self.fail("run did not complete")

    def test_static_assets_and_security_headers(self):
        for path in ("/", "/app.js", "/style.css"):
            with self.request(path) as response:
                self.assertEqual(response.status, 200)
                self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
                self.assertTrue(response.read())

    @unittest.skipUnless((ROOT / 'data/packs/nemotron-japan-sample.jsonl').is_file(), 'optional public sample: python3 tools/prepare_public_sample.py')
    def test_actual_dataset_preview_filter_and_pagination(self):
        packs = self.json("/api/packs")
        self.assertTrue({"synthetic-fixture", "nemotron-japan-sample"} <= {p["id"] for p in packs})
        preview = self.json("/api/personas?pack=nemotron-japan-sample")
        self.assertEqual((len(preview["items"]), preview["matched_count"]), (20, 53))
        later = self.json("/api/personas?pack=nemotron-japan-sample&offset=40")
        self.assertEqual(len(later["items"]), 13)
        filtered = self.json("/api/personas?pack=synthetic-fixture&age_min=40")
        self.assertEqual(filtered["matched_count"], 3)

    def test_complete_ui_api_flow_and_all_exports(self):
        spec = self.json("/api/default-experiment")
        created = self.json("/api/runs", {"dataset_id": "synthetic-fixture", "backend": "mock", "spec": spec})
        id = created["id"]
        self.assertEqual(self.complete(id)["cursor"], 56)
        report = self.json(f"/api/runs/{id}/report")
        self.assertEqual(report["paired_transition_count"], 4)
        self.assertIn({"from": "decline", "to": "buy", "count": 1}, report["paired_purchase_transitions"])
        for format in ("json", "csv", "md"):
            with self.request(f"/api/runs/{id}/export?format={format}") as response:
                self.assertIn("attachment", response.headers["Content-Disposition"])
                self.assertIn(b"fixture", response.read())
        self.assertEqual(self.json(f"/api/runs/{id}/spec")["spec"], spec)
        self.json(f"/api/runs/{id}/resume", {})
        self.assertEqual(self.complete(id)["cursor"], 56)
        self.assertTrue(any(r["id"] == id for r in self.json("/api/runs")))

    def test_invalid_inputs_cross_origin_host_and_paths_are_rejected(self):
        spec = self.json("/api/default-experiment")
        for path, body, headers in (
            ("/api/runs", {"dataset_id": "synthetic-fixture", "backend": "mock", "spec": None}, {}),
            ("/api/runs", {}, {"Origin": "https://untrusted.example"}),
            ("/api/runs", {}, {"X-Persona-Lab": "wrong"}),
            ("/api/packs", None, {"Host": "untrusted.example"}),
            ("/api/personas?pack=..%2F..%2Fetc%2Fpasswd", None, {}),
            ("/api/personas?pack=synthetic-fixture&age_min=60&age_max=20", None, {}),
            ("/api/import", {"dataset": "nemotron-japan-viewer", "url": "file:///etc/passwd"}, {}),
            ("/api/upload", {"filename": "../../outside.json", "content": "bad upload"}, {}),
        ):
            with self.subTest(path=path), self.assertRaises(urllib.error.HTTPError) as error:
                self.request(path, body, headers)
            self.assertEqual(error.exception.code, 400)

    def test_empty_filter_is_reported_and_stored_run_can_recover(self):
        spec = self.json("/api/default-experiment")
        spec["panel"] = {"selection": "filter", "query": "no-profile-can-match-this-text"}
        id = self.json("/api/runs", {"dataset_id": "synthetic-fixture", "backend": "mock", "spec": spec})["id"]
        for _ in range(100):
            status = self.json("/api/runs/" + id)
            if not status["active"]:
                break
            time.sleep(.03)
        self.assertEqual(status["status"], "failed")
        self.assertIn("empty", status["error"])

    def test_saved_detail_exposes_original_conditions_choices_and_verified_profile(self):
        spec = self.json("/api/default-experiment")
        id = self.json("/api/runs", {"dataset_id": "synthetic-fixture", "backend": "mock", "spec": spec})["id"]
        self.complete(id)
        record = self.json(f"/api/runs/{id}/report")["examples"][0]
        detail = self.json(f"/api/runs/{id}/jobs/{record['job_id']}")
        self.assertEqual(detail["question"], spec["questions"][0])
        self.assertEqual(detail["product"], spec["products"][0])
        self.assertEqual(detail["assumptions"], spec["assumptions"])
        self.assertEqual(detail["persona"]["content_hash"], record["persona_content_hash"])
        self.assertIn("persona", detail["persona"]["raw"])
        with self.assertRaises(urllib.error.HTTPError):
            self.request(f"/api/runs/{id}/jobs/invalid")

    def test_detail_rejects_changed_source_instead_of_showing_it_as_original(self):
        spec = self.json("/api/default-experiment")
        id = self.json("/api/runs", {"dataset_id": "synthetic-fixture", "backend": "mock", "spec": spec})["id"]
        self.complete(id)
        record = self.json(f"/api/runs/{id}/report")["examples"][0]
        path = self.root / "data/packs/synthetic-fixture.jsonl"
        original = path.read_text()
        try:
            rows = [json.loads(line) for line in original.splitlines()]
            rows[0]["persona"] = "Changed after inference"
            path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.request(f"/api/runs/{id}/jobs/{record['job_id']}")
            self.assertIn("original input cannot be verified", error.exception.read().decode())
        finally:
            path.write_text(original)

    def test_parquet_configuration_and_arbitrary_input_are_rejected(self):
        configuration = self.json('/api/parquet-config')
        self.assertEqual(len(configuration['official_shards']), 8)
        self.assertEqual(configuration['available'], pa is not None)
        for body in (
            {'kind': 'official_parquet', 'shard': '../../outside.parquet'},
            {'kind': 'official_parquet', 'shard': 'train-00000-of-00008.parquet', 'url': 'https://untrusted.example'},
            {'kind': 'local_parquet', 'filename': '../outside.parquet'},
            {'kind': 'local_parquet', 'filename': 'missing.parquet'},
        ):
            with self.subTest(body=body), self.assertRaises(urllib.error.HTTPError) as error:
                self.request('/api/parquet-imports', body)
            self.assertEqual(error.exception.code, 400)

    @unittest.skipUnless(pa is not None, 'optional PyArrow requires .venv-data')
    def test_local_parquet_import_catalog_and_saved_condition_flow(self):
        inbox = self.root / 'data/inbox'; inbox.mkdir(exist_ok=True)
        source = json.loads((self.root / 'data/packs/synthetic-fixture.json').read_text())
        source.update(source_id='persona-lab/http-parquet-fixture', version='explicit-http-fixture-v1')
        rows = [{'uuid': f'explicit-http-fixture-{i}', 'persona': f'Explicit project synthetic person {i}', 'age': 25, 'prefecture': 'fixture_region'} for i in range(73)]
        pq.write_table(pa.Table.from_pylist(rows), inbox / 'explicit-fixture.parquet', row_group_size=17)
        (inbox / 'explicit-fixture.parquet.source.json').write_text(json.dumps(source))
        self.assertTrue(any(item['filename'] == 'explicit-fixture.parquet' for item in self.json('/api/parquet-config')['local_files']))
        identifier = self.json('/api/parquet-imports', {'kind': 'local_parquet', 'filename': 'explicit-fixture.parquet'})['id']
        for _ in range(100):
            status = self.json('/api/parquet-imports/' + identifier)
            if not status['active']: break
            time.sleep(.03)
        self.assertEqual((status['status'], status['rows']), ('completed', 73), status)
        pack = status['pack_id']; page = self.json(f'/api/personas?pack={pack}&offset=60')
        self.assertEqual((page['matched_count'], len(page['items'])), (73, 13))
        spec = self.json('/api/default-experiment')
        spec['panel'] = {'selection': 'filter', 'query': rows[-1]['uuid']}
        run = self.json('/api/runs', {'dataset_id': pack, 'backend': 'mock', 'spec': spec})['id']
        self.assertEqual(self.complete(run)['cursor'], 14)
        record = self.json(f'/api/runs/{run}/report')['examples'][0]
        detail = self.json(f'/api/runs/{run}/jobs/{record["job_id"]}')
        self.assertEqual(detail['persona']['raw'], rows[-1])
        self.assertEqual(detail['source']['license_id'], source['license_id'])


if __name__ == "__main__":
    unittest.main()
