#!/usr/bin/env python3
"""Download a bounded, complete prefix from the official public persona API.

This preparation tool uses only the Python standard library. The resulting pool
is a prefix of the upstream Viewer, not a representative population sample.
"""

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DATASET = "nvidia/Nemotron-Personas-Japan"
CARD_URL = f"https://huggingface.co/datasets/{DATASET}"
INFO_URL = f"https://huggingface.co/api/datasets/{DATASET}"
LEGACY_SHA256 = "826d6afc3b33ada62445f3fe5bb0db38dce7719a32d826f9758018e4a35fbcb2"
FIELDS = (
    "uuid", "professional_persona", "sports_persona", "arts_persona",
    "travel_persona", "culinary_persona", "persona", "cultural_background",
    "skills_and_expertise", "skills_and_expertise_list", "hobbies_and_interests",
    "hobbies_and_interests_list", "career_goals_and_ambitions", "sex", "age",
    "marital_status", "education_level", "occupation", "region", "area",
    "prefecture", "country",
)
REQUEST_LOCK = threading.Lock()
NEXT_REQUEST_AT = 0.0


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def atomic_write(path, content, *, overwrite=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(content)
    try:
        temporary.chmod(0o644)
        if overwrite:
            os.replace(temporary, path)
        else:
            os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def preserve_pool(output_dir, count, data):
    """Reuse identical bytes; changed pools get a new immutable SHA-named file."""
    sha = digest(data)
    for name in (f"nemotron-japan-pool-{count}.jsonl",
                 f"nemotron-japan-pool-{count}-{sha}.jsonl"):
        path = output_dir / name
        if path.exists():
            if digest(path.read_bytes()) == sha:
                return name
            continue
        try:
            atomic_write(path, data, overwrite=False)
        except FileExistsError:
            # Another preparation may have published this filename meanwhile.
            if digest(path.read_bytes()) == sha:
                return name
        else:
            return name
    raise ValueError("Existing pool files differ from their requested content; nothing was overwritten")


def fetch(url):
    global NEXT_REQUEST_AT
    for attempt in range(4):
        try:
            with REQUEST_LOCK:
                time.sleep(max(0, NEXT_REQUEST_AT - time.monotonic()))
                NEXT_REQUEST_AT = time.monotonic() + 1.25
            request = Request(url, headers={"User-Agent": "Persona-Lab-data-preparation/1"})
            with urlopen(request, timeout=45) as response:
                body = response.read(8_000_001)
            if len(body) > 8_000_000:
                raise ValueError("API response exceeds the preparation tool's 8 MB limit")
            return json.loads(body), body
        except HTTPError as error:
            if error.code not in (429, 500, 502, 503, 504) or attempt == 3:
                raise
            retry_after = error.headers.get("Retry-After")
            try:
                wait = float(retry_after) if retry_after else (60 if error.code == 429 else 2 ** attempt)
            except ValueError:
                wait = (parsedate_to_datetime(retry_after) - datetime.now(timezone.utc)).total_seconds()
            wait = max(1, wait)
            if wait > 300:
                raise ValueError("Server requested a wait longer than this bounded download permits") from error
            with REQUEST_LOCK:
                NEXT_REQUEST_AT = max(NEXT_REQUEST_AT, time.monotonic() + wait)
            print(f"HTTP {error.code}; waiting at least {wait:g} seconds before retry", flush=True)
        except (URLError, TimeoutError):
            if attempt == 3:
                raise
            wait = 2 ** attempt
        time.sleep(wait)
    raise AssertionError("Unreachable retry state")


def fetch_page(bounds):
    offset, length = bounds
    url = "https://datasets-server.huggingface.co/rows?" + urlencode({
        "dataset": DATASET, "config": "default", "split": "train",
        "offset": offset, "length": length,
    })
    result, payload = fetch(url)
    rows = result.get("rows", [])
    if len(rows) != length or result.get("partial"):
        raise ValueError(f"Incomplete API page at offset {offset}")
    if any(row.get("truncated_cells") for row in rows):
        if length == 1:
            raise ValueError(f"Truncated source row at offset {offset}; no output written")
        half = length // 2
        left, right = fetch_page((offset, half)), fetch_page((offset + half, length - half))
        return left[0] + right[0], left[1] + right[1]
    if [row.get("row_idx") for row in rows] != list(range(offset, offset + length)):
        raise ValueError(f"Unexpected source row indices at offset {offset}")
    for record in rows:
        row = record["row"]
        if set(row) != set(FIELDS) or not isinstance(row["uuid"], str) or not row["uuid"]:
            raise ValueError(f"Incomplete source fields at offset {record['row_idx']}")
        if not isinstance(row["age"], int):
            raise ValueError(f"Missing source age at offset {record['row_idx']}")
    page = {"url": url, "offset": offset, "length": length,
            "payload_bytes": len(payload), "payload_sha256": digest(payload),
            "upstream_record_count": result["num_rows_total"], "truncated_cells": 0}
    return [record["row"] for record in rows], [page]


def prepare(args):
    if not 1 <= args.count <= 10_000 or not 1 <= args.page_size <= 100 or not 1 <= args.workers <= 4:
        raise ValueError("count: 1..10000; page size: 1..100; workers: 1..4")
    legacy_path = args.output_dir / "nemotron-japan-sample.jsonl"
    legacy_bytes = legacy_path.read_bytes()
    if digest(legacy_bytes) != LEGACY_SHA256:
        raise ValueError("Frozen 53-person source changed; refusing to replace metadata")
    legacy_manifest_path = args.output_dir / "nemotron-japan-53.json"
    legacy_manifest = (legacy_manifest_path if legacy_manifest_path.exists()
                       else args.output_dir / "nemotron-japan-sample.json").read_bytes()
    legacy = json.loads(legacy_manifest)
    if legacy["local_sha256"] != LEGACY_SHA256 or legacy["record_count"] != 53:
        raise ValueError("The frozen 53-person metadata is unavailable")
    info, _ = fetch(INFO_URL)
    if info.get("cardData", {}).get("license") != "cc-by-4.0":
        raise ValueError("Upstream license differs from the approved CC BY 4.0 source")
    bounds = [(offset, min(args.page_size, args.count - offset))
              for offset in range(0, args.count, args.page_size)]
    rows, pages = [], []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for batch, source_pages in pool.map(fetch_page, bounds):
            rows.extend(batch)
            pages.extend(source_pages)
            print(f"Downloaded {len(rows)}/{args.count} complete source rows", flush=True)
    uuids = {row["uuid"] for row in rows}
    if len(rows) != args.count or len(uuids) != args.count:
        raise ValueError("Source row count or unique UUID count differs from the requested count")
    totals = {page["upstream_record_count"] for page in pages}
    if len(totals) != 1:
        raise ValueError("Upstream row count changed during download")
    data = "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
                   for row in rows).encode()
    data_file = preserve_pool(args.output_dir, args.count, data)
    retrieved = datetime.now(timezone.utc).isoformat()
    metadata = {key: legacy[key] for key in (
        "schema_version", "source_id", "url", "license_id", "license_url", "origin", "attribution",
    )}
    metadata.update({
        "version": f"rows-sha256:{digest(data)}", "name": f"NVIDIA 일본 · {args.count:,}명",
        "record_count": len(rows), "data_file": data_file,
        "upstream_revision_observed": info["sha"], "upstream_info_url": INFO_URL,
        "fetch_url": "https://datasets-server.huggingface.co/rows", "retrieved_at": retrieved,
        "upstream_record_count": next(iter(totals)), "upstream_size_card_gb": 1.73,
        "source_config": "default", "source_split": "train", "source_offset": 0,
        "payload_bytes": len(data), "local_sha256": digest(data),
        "revision_binding": "Viewer rows endpoint is mutable main; the local JSONL SHA-256 is pinned. "
                            "Upstream repository revision was observed separately, not bound to API rows.",
        "modifications": "Converted complete returned row objects to UTF-8 JSONL without altering field "
                         "values. No truncated rows retained. This contiguous Viewer prefix is not a "
                         "random or representative sample of the full dataset.",
    })
    receipt = {
        "status": "passed", "retrieved_at": retrieved, "tool": "tools/prepare_persona_pool.py",
        "source_url": CARD_URL, "upstream_revision_observed": info["sha"],
        "revision_binding": metadata["revision_binding"], "record_count": len(rows),
        "unique_uuid_count": len(uuids), "truncated_rows": 0, "field_count": len(FIELDS),
        "data_file": str(args.output_dir / data_file), "local_sha256": digest(data),
        "payload_bytes": len(data), "legacy_sha256": digest(legacy_bytes),
        "legacy_record_count": len(legacy_bytes.splitlines()), "legacy_preserved": True,
        "all_legacy_uuids_present": all(json.loads(line)["uuid"] in uuids
                                       for line in legacy_bytes.splitlines()),
        "request_interval_seconds": 1.25, "max_workers": args.workers,
        "max_request_attempts": 4, "rate_limit_backoff_seconds_without_header": 60,
        "empty_field_counts": {field: sum(row[field] in (None, "") for row in rows) for field in FIELDS},
        "distributions": {field: dict(sorted(Counter(row[field] for row in rows).items()))
                          for field in ("sex", "age", "prefecture", "region", "country")},
        "limits": f"The bundled pool is the first complete {args.count:,} Viewer rows. Runtime sampling "
                  "is only within this pool; neither the prefix nor filtered samples imply population representation.",
        "pages": pages,
    }
    # Commit the active manifest only after all complete output files are ready.
    atomic_write(legacy_manifest_path, legacy_manifest)
    atomic_write(args.receipt, encoded(receipt))
    atomic_write(args.output_dir / "nemotron-japan-sample.json", encoded(metadata))
    if digest(legacy_path.read_bytes()) != LEGACY_SHA256:
        raise ValueError("Frozen legacy source changed during preparation")
    print(json.dumps({"status": "passed", "count": len(rows), "bytes": len(data),
                      "sha256": digest(data), "receipt": str(args.receipt)}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=10_000)
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "assets/data")
    parser.add_argument("--receipt", type=Path, default=ROOT / "verification/persona-pool.json")
    prepare(parser.parse_args())
