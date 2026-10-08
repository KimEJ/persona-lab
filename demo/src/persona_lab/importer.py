"""Fetch only a small, fixed public NVIDIA Viewer response; no arbitrary URLs."""

import hashlib
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from .adapter import normalize, EXPECTED_FIELDS
from .contracts import canonical, require

VIEWER_URL = "https://datasets-server.huggingface.co/first-rows?dataset=nvidia%2FNemotron-Personas-Japan&config=default&split=train"
METADATA_URL = "https://huggingface.co/api/datasets/nvidia/Nemotron-Personas-Japan"
MAX_BYTES = 1048576


def _read_public_json(url: str) -> tuple[dict, bytes]:
    require(url in {VIEWER_URL, METADATA_URL}, "only the fixed official dataset endpoints are supported")
    with urllib.request.urlopen(url, timeout=30) as response:
        body = response.read(MAX_BYTES + 1)
    require(len(body) <= MAX_BYTES, "public response exceeds the 1MB import limit")
    payload = json.loads(body)
    require(isinstance(payload, dict), "public response must be an object")
    return payload, body


def fetch_sample(root: Path) -> dict:
    metadata, _ = _read_public_json(METADATA_URL)
    require(metadata.get("id") == "nvidia/Nemotron-Personas-Japan", "unexpected dataset identity")
    require(metadata.get("cardData", {}).get("license") == "cc-by-4.0", "dataset license changed; review before importing")
    payload, body = _read_public_json(VIEWER_URL)
    fields = {field["name"] for field in payload.get("features", [])}
    require(set(EXPECTED_FIELDS) <= fields, "Viewer schema is missing required source fields")
    rows = payload.get("rows")
    require(isinstance(rows, list) and bool(rows), "Viewer returned no rows")
    payload_hash = hashlib.sha256(body).hexdigest()
    id = "nemotron-japan-viewer-" + payload_hash[:12]
    source = {"schema_version": "0.1", "source_id": "nvidia/Nemotron-Personas-Japan", "version": "viewer-sha256:" + payload_hash,
      "url": "https://huggingface.co/datasets/nvidia/Nemotron-Personas-Japan", "license_id": "CC-BY-4.0", "license_url": "https://creativecommons.org/licenses/by/4.0/", "origin": "upstream_synthetic",
      "attribution": "NVIDIA; Fujita, Gong, Ogushi, Yamamoto, Suhara, Corneil and Meyer (2025), Nemotron-Personas-Japan: Synthetic Personas Aligned to Real-World Distributions",
      "name": "NVIDIA 일본 · 가져온 Viewer 샘플", "data_file": id + ".jsonl", "record_count": len(rows), "upstream_record_count": 1000000,
      "retrieved_at": datetime.now(timezone.utc).isoformat(), "upstream_revision_observed": metadata.get("sha"), "fetch_url": VIEWER_URL, "payload_bytes": len(body),
      "revision_binding": "Mutable Viewer endpoint; local payload hash is pinned and upstream revision observed separately.",
      "modifications": "Returned row objects converted to JSONL without altering values; truncated cells cause import rejection. Preview is not random or representative."}
    normalized = []
    seen = set()
    for entry in rows:
        require(isinstance(entry, dict) and not entry.get("truncated_cells"), "truncated or invalid Viewer row; import rejected")
        person = normalize(entry.get("row"), source)
        require(person.uuid not in seen, "duplicate UUID in Viewer response")
        seen.add(person.uuid)
        normalized.append(canonical(person.raw))
    data = ("\n".join(normalized) + "\n").encode()
    source["local_sha256"] = hashlib.sha256(data).hexdigest()
    directory = root.resolve() / "data/packs"
    directory.mkdir(parents=True, exist_ok=True)
    manifest, records = directory / (id + ".json"), directory / source["data_file"]
    if manifest.exists():
        existing = json.loads(manifest.read_text())
        require(records.exists() and hashlib.sha256(records.read_bytes()).hexdigest() == existing["local_sha256"], "existing imported pack was modified")
        return {**existing, "id": id, "already_installed": True}
    # Publish manifest last; the catalog cannot see a half-written pack.
    temporary_records = records.with_suffix(".jsonl.tmp")
    temporary_records.write_bytes(data)
    temporary_records.replace(records)
    temporary_manifest = manifest.with_suffix(".json.tmp")
    temporary_manifest.write_text(canonical(source), encoding="utf-8")
    temporary_manifest.replace(manifest)
    return {**source, "id": id, "already_installed": False}
