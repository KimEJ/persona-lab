import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from persona_lab.importer import fetch_sample, _read_public_json
from persona_lab.adapter import EXPECTED_FIELDS
from persona_lab.contracts import ContractError


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.meta = {"id": "nvidia/Nemotron-Personas-Japan", "sha": "observed-test-revision", "cardData": {"license": "cc-by-4.0"}}
        self.payload = {"features": [{"name": name} for name in EXPECTED_FIELDS], "rows": [{"row": {"uuid": "source-uuid", "age": 42, "persona": None}, "truncated_cells": []}]}

    def import_payload(self):
        body = json.dumps(self.payload).encode()
        with patch("persona_lab.importer._read_public_json", side_effect=[(self.meta, b"metadata"), (self.payload, body)]):
            return fetch_sample(self.root)

    def test_import_preserves_original_values_and_does_not_overwrite_existing_pack(self):
        pack = self.import_payload()
        self.assertEqual(pack["record_count"], 1)
        path = self.root / "data/packs" / pack["data_file"]
        self.assertEqual(json.loads(path.read_text()), self.payload["rows"][0]["row"])
        again = self.import_payload()
        self.assertTrue(again["already_installed"])
        self.assertEqual(again["retrieved_at"], pack["retrieved_at"])

    def test_arbitrary_url_is_rejected_before_network(self):
        for url in ("file:///etc/passwd", "http://127.0.0.1:8081", "https://untrusted.example"):
            with self.subTest(url=url), self.assertRaises(ContractError):
                _read_public_json(url)

    def test_license_change_truncation_missing_uuid_and_duplicates_rejected(self):
        for case in ("license", "truncated", "uuid", "duplicate"):
            with self.subTest(case=case):
                self.setUp()
                if case == "license": self.meta["cardData"]["license"] = "changed-license"
                if case == "truncated": self.payload["rows"][0]["truncated_cells"] = ["persona"]
                if case == "uuid": self.payload["rows"][0]["row"].pop("uuid")
                if case == "duplicate": self.payload["rows"] *= 2
                with self.assertRaises(ContractError):
                    self.import_payload()
                self.assertFalse((self.root / "data/packs").exists())

    def test_modified_existing_records_are_detected(self):
        pack = self.import_payload()
        (self.root / "data/packs" / pack["data_file"]).write_text('{"uuid":"tampered"}\n')
        with self.assertRaisesRegex(ContractError, "modified"):
            self.import_payload()


if __name__ == "__main__": unittest.main()
