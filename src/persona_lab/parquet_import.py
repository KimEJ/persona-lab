"""Pinned shard download and bounded row-group ingestion with disk checkpoints.

PyArrow is optional and imported only inside run_import. This module never
accepts arbitrary network URLs. Local CLI paths require explicit source metadata.
"""
import fcntl
import hashlib
import json
import os
import re
import shutil
import sqlite3
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from .adapter import normalize, EXPECTED_FIELDS
from .contracts import canonical, digest, require, validate_source, ContractError

REVISION = 'f1f37019d8497143c507b3deb547e65646de2ab7'
DATASET = 'nvidia/Nemotron-Personas-Japan'
MAX_BATCH_BYTES = 8 * 1024 * 1024
MAX_ROW_GROUP_BYTES = 128 * 1024 * 1024


def now(): return datetime.now(timezone.utc).isoformat()


def file_hash(path, limit=None):
    sha = hashlib.sha256(); remaining = limit
    with Path(path).open('rb') as stream:
        while remaining is None or remaining > 0:
            block = stream.read(1024 * 1024 if remaining is None else min(1024 * 1024, remaining))
            if not block: break
            sha.update(block)
            if remaining is not None: remaining -= len(block)
    require(remaining in (None, 0), 'checkpoint file is shorter than its committed prefix')
    return sha


def official_shards(root):
    catalog = json.loads((Path(root) / 'data/official-shards.json').read_text())
    require(catalog['dataset'] == DATASET and catalog['revision'] == REVISION and catalog['license'] == 'CC-BY-4.0', 'official catalog identity changed')
    return catalog['files']


def official_source(item):
    return {'schema_version': '0.1', 'source_id': DATASET, 'version': f'parquet:{REVISION}:{item["sha256"]}', 'url': f'https://huggingface.co/datasets/{DATASET}', 'license_id': 'CC-BY-4.0', 'license_url': 'https://creativecommons.org/licenses/by/4.0/', 'origin': 'upstream_synthetic', 'attribution': 'NVIDIA; Fujita, Gong, Ogushi, Yamamoto, Suhara, Corneil and Meyer (2025), Nemotron-Personas-Japan: Synthetic Personas Aligned to Real-World Distributions', 'upstream_record_count': 1000000, 'upstream_revision': REVISION, 'shard': item['filename'], 'parquet_sha256': item['sha256'], 'parquet_bytes': item['bytes'], 'name': 'NVIDIA 일본 · 원본 ' + item['filename'], 'modifications': 'Parquet row values converted to canonical JSONL. One UUID remains one person; source strings/nulls and additional fields are preserved. Selected shard is not a representative random panel.'}


def create_import(root, *, shard=None, local_path=None, source=None, batch_size=256):
    root = Path(root).resolve()
    require(type(batch_size) is int and 1 <= batch_size <= 4096, 'import batch must be 1 to 4096 rows; this is not a panel-size cap')
    require((shard is None) != (local_path is None), 'choose an official shard or explicit local file')
    if shard is not None:
        require(re.fullmatch(r'train-0000[0-7]-of-00008\.parquet', shard) is not None, 'invalid official shard')
        item = next((item for item in official_shards(root) if item['filename'] == shard), None)
        require(item is not None and 0 < item['bytes'] < 1024 ** 3 and re.fullmatch('[a-f0-9]{64}', item['sha256']), 'invalid pinned shard metadata')
        spec = {'kind': 'official_parquet', 'item': item, 'source': official_source(item), 'batch_size': batch_size}
    else:
        path = Path(local_path).resolve()
        require(path.is_file() and path.suffix.lower() == '.parquet', 'local input must be a Parquet file')
        validate_source(source)
        checksum = file_hash(path).hexdigest()
        provided = dict(source)
        provided.update(version=source['version'] + '|parquet-sha256:' + checksum, source_provided_version=source['version'], parquet_sha256=checksum, parquet_bytes=path.stat().st_size, name=source.get('name', '명시적 로컬 Parquet'), provenance_verification='Local file SHA-256 pinned; publisher and license are explicitly supplied metadata, not independently verified.')
        spec = {'kind': 'local_parquet', 'input_path': str(path), 'source': provided, 'batch_size': batch_size}
    identifier = digest({'import_contract': 'parquet-import-v1', 'spec': spec})[:32]
    directory = root / 'imports' / identifier
    directory.mkdir(parents=True, exist_ok=True)
    manifest = directory / 'manifest.json'
    if manifest.exists(): require(json.loads(manifest.read_text()) == spec, 'import identity collision')
    else:
        temporary = manifest.with_suffix('.tmp'); temporary.write_text(canonical(spec)); temporary.replace(manifest)
    return identifier


def open_checkpoint(directory):
    db = sqlite3.connect(Path(directory) / 'checkpoint.sqlite', timeout=5)
    db.execute('PRAGMA journal_mode=WAL'); db.execute('PRAGMA synchronous=FULL'); db.execute('PRAGMA cache_size=-4096')
    db.executescript('''CREATE TABLE IF NOT EXISTS metadata(id INTEGER PRIMARY KEY CHECK(id=1),payload TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS people(uuid TEXT PRIMARY KEY, ordinal INTEGER UNIQUE NOT NULL, byte_offset INTEGER NOT NULL, byte_length INTEGER NOT NULL, age INTEGER, prefecture TEXT, search_fold TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS people_filter ON people(prefecture,age);''')
    return db


def _load(db):
    row = db.execute('SELECT payload FROM metadata WHERE id=1').fetchone()
    return json.loads(row[0]) if row else None


def _commit(db, metadata):
    db.execute('INSERT OR REPLACE INTO metadata VALUES (1,?)', (canonical(metadata),)); db.commit()


def read_import_status(root, identifier):
    require(re.fullmatch('[a-f0-9]{32}', identifier) is not None, 'invalid import id')
    directory = Path(root) / 'imports' / identifier
    require((directory / 'manifest.json').is_file(), 'import not found')
    if not (directory / 'checkpoint.sqlite').exists(): return {'id': identifier, 'status': 'preparing', 'phase': 'preparing', 'rows': 0, 'total_rows': None, 'download_bytes': 0, 'error': None}
    try:
        with sqlite3.connect(directory / 'checkpoint.sqlite') as db: metadata = _load(db)
    except sqlite3.OperationalError as error:
        if 'no such table: metadata' not in str(error): raise
        metadata = None
    return {'id': identifier, **(metadata or {'status': 'preparing', 'phase': 'preparing', 'rows': 0, 'total_rows': None, 'download_bytes': 0, 'error': None})}


def import_locked(root, identifier):
    directory = Path(root) / 'imports' / identifier
    with (directory / 'writer.lock').open('a') as lock:
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: return True
        fcntl.flock(lock, fcntl.LOCK_UN)
        return False


def _license_check():
    url = f'https://huggingface.co/api/datasets/{DATASET}/revision/{REVISION}'
    with urllib.request.urlopen(url, timeout=30) as response: body = response.read(1048577)
    require(len(body) <= 1048576, 'metadata exceeds 1MB')
    data = json.loads(body)
    require(data.get('id') == DATASET and data.get('sha') == REVISION, 'pinned dataset metadata mismatch')
    require(data.get('cardData', {}).get('license') == 'cc-by-4.0', 'dataset license changed; review before import')


def _download(directory, spec, db, metadata, cancelled, progress):
    item = spec['item']; final = directory / 'source.parquet'; part = directory / 'source.parquet.part'
    if final.exists():
        require(final.stat().st_size == item['bytes'] and file_hash(final).hexdigest() == item['sha256'], 'downloaded shard checksum mismatch')
        return final, metadata
    if not metadata.get('license_checked_at'):
        _license_check(); metadata = {**metadata, 'license_checked_at': now()}; _commit(db, metadata)
    require(shutil.disk_usage(directory).free >= item['bytes'] * 5 + 128 * 1024 ** 2, 'not enough free disk for shard and import output')
    offset = metadata['download_bytes']
    if not part.exists(): require(offset == 0, 'download checkpoint file missing'); part.touch()
    require(part.stat().st_size >= offset, 'download is shorter than committed checkpoint')
    with part.open('r+b') as stream: stream.truncate(offset)
    checksum = file_hash(part)
    require(checksum.hexdigest() == metadata['download_sha256'], 'download prefix changed; resume rejected')
    if offset < item['bytes']:
        url = f'https://huggingface.co/datasets/{DATASET}/resolve/{REVISION}/data/{item["filename"]}'
        request = urllib.request.Request(url, headers={'Range': f'bytes={offset}-', 'Accept-Encoding': 'identity'})
        with urllib.request.urlopen(request, timeout=30) as response, part.open('ab') as stream:
            host = urlparse(response.geturl()).hostname or ''
            require(host == 'huggingface.co' or host.endswith(('.hf.co', '.xethub.hf.co')), 'unexpected official download redirect')
            if offset:
                require(response.status == 206 and response.headers.get('Content-Range', '').startswith(f'bytes {offset}-') and response.headers['Content-Range'].endswith('/' + str(item['bytes'])), 'server did not honor safe range resume')
            else: require(response.status in (200, 206), 'unexpected download response')
            while offset < item['bytes']:
                if cancelled(): return None, metadata
                block = response.read(min(1024 * 1024, item['bytes'] - offset))
                require(bool(block), 'shard download ended early')
                stream.write(block); stream.flush(); os.fsync(stream.fileno()); checksum.update(block); offset += len(block)
                metadata = {**metadata, 'status': 'running', 'phase': 'downloading', 'download_bytes': offset, 'download_total_bytes': item['bytes'], 'download_sha256': checksum.hexdigest()}
                _commit(db, metadata); progress(metadata)
    require(offset == item['bytes'] and checksum.hexdigest() == item['sha256'], 'official shard SHA-256 mismatch')
    part.replace(final)
    return final, metadata


def _publish(root, directory, spec, metadata, db):
    source = dict(spec['source'])
    pack_id = 'parquet-' + digest({'source': source['source_id'], 'version': source['version']})[:20]
    packs = root / 'data/packs'; packs.mkdir(parents=True, exist_ok=True)
    manifest = packs / (pack_id + '.json'); output = directory / 'records.jsonl'
    data_path = packs / (pack_id + '.jsonl'); catalog_path = packs / (pack_id + '.catalog.sqlite')
    checksum = file_hash(output).hexdigest()
    require(checksum == metadata['output_sha256'], 'output changed before publication')
    if manifest.exists():
        existing = json.loads(manifest.read_text())
        require(existing['local_sha256'] == checksum and file_hash(data_path).hexdigest() == checksum, 'existing pack changed; never overwrite')
        return pack_id
    if data_path.exists(): require(file_hash(data_path).hexdigest() == checksum, 'unpublished target differs; never overwrite')
    else: os.link(output, data_path)
    if not catalog_path.exists():
        temporary = catalog_path.with_suffix('.tmp')
        with sqlite3.connect(temporary) as destination: db.backup(destination, pages=256)
        temporary.replace(catalog_path)
    with sqlite3.connect(catalog_path) as catalog:
        require(catalog.execute('SELECT COUNT(*) FROM people').fetchone()[0] == metadata['rows'] and _load(catalog)['output_sha256'] == checksum, 'catalog checkpoint mismatch')
    source.update(data_file=data_path.name, catalog_file=catalog_path.name, record_count=metadata['rows'], local_sha256=checksum, retrieved_at=metadata['created_at'], row_groups=metadata['row_groups'], import_contract='parquet-import-v1')
    temporary = manifest.with_suffix('.tmp'); temporary.write_text(canonical(source)); temporary.replace(manifest)
    return pack_id


def run_import(root, identifier, *, cancelled=lambda: False, progress=lambda _: None, max_batches=None):
    import pyarrow as pa
    import pyarrow.parquet as pq
    root = Path(root).resolve(); directory = root / 'imports' / identifier
    require(re.fullmatch('[a-f0-9]{32}', identifier) is not None and (directory / 'manifest.json').is_file(), 'import not found')
    spec = json.loads((directory / 'manifest.json').read_text())
    require(max_batches is None or type(max_batches) is int and max_batches > 0, 'max_batches must be positive')
    with (directory / 'writer.lock').open('a') as lock:
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error: raise ContractError('another import writer is active') from error
        db = open_checkpoint(directory)
        try:
            metadata = _load(db)
            if metadata is None:
                metadata = {'spec_hash': digest(spec), 'status': 'running', 'phase': 'preparing', 'created_at': now(), 'rows': 0, 'total_rows': None, 'row_group': 0, 'row_offset': 0, 'output_bytes': 0, 'output_sha256': hashlib.sha256().hexdigest(), 'download_bytes': 0, 'download_sha256': hashlib.sha256().hexdigest(), 'error': None}
                _commit(db, metadata)
            require(metadata['spec_hash'] == digest(spec), 'import spec changed; resume rejected')
            if metadata['status'] == 'completed':
                pack = root / 'data/packs' / (metadata['pack_id'] + '.json')
                require(pack.is_file(), 'published pack missing')
                published = json.loads(pack.read_text())
                require(file_hash(root / 'data/packs' / published['data_file']).hexdigest() == published['local_sha256'], 'published pack changed; never overwrite')
                return metadata
            metadata = {**metadata, 'status': 'running', 'error': None}; _commit(db, metadata)
            if spec['kind'] == 'official_parquet':
                path, metadata = _download(directory, spec, db, metadata, cancelled, progress)
                if path is None:
                    metadata = {**metadata, 'status': 'paused'}; _commit(db, metadata); return metadata
            else:
                path = Path(spec['input_path'])
                require(path.is_file() and file_hash(path).hexdigest() == spec['source']['parquet_sha256'], 'local source changed; resume rejected')
            parquet = pq.ParquetFile(path, pre_buffer=False, memory_map=False, thrift_string_size_limit=64 * 1024 ** 2, thrift_container_size_limit=1000000)
            require(parquet.metadata.num_rows > 0 and 'uuid' in parquet.schema_arrow.names, 'empty Parquet or missing UUID column')
            if spec['kind'] == 'official_parquet': require(set(EXPECTED_FIELDS) <= set(parquet.schema_arrow.names), 'official schema is missing source fields')
            metadata = {**metadata, 'total_rows': parquet.metadata.num_rows, 'row_groups': parquet.num_row_groups, 'status': 'running', 'phase': 'converting', 'pyarrow': pa.__version__}
            _commit(db, metadata); progress(metadata)
            require(db.execute('SELECT COUNT(*) FROM people').fetchone()[0] == metadata['rows'], 'UUID index/checkpoint count mismatch')
            output = directory / 'records.jsonl'
            if not output.exists(): require(metadata['output_bytes'] == 0, 'output checkpoint missing'); output.touch()
            require(output.stat().st_size >= metadata['output_bytes'], 'output is shorter than checkpoint')
            with output.open('r+b') as stream: stream.truncate(metadata['output_bytes'])
            checksum = file_hash(output)
            require(checksum.hexdigest() == metadata['output_sha256'], 'output prefix changed; resume rejected')
            completed_batches = 0
            with output.open('ab') as stream:
                for group_index in range(metadata['row_group'], parquet.num_row_groups):
                    require(parquet.metadata.row_group(group_index).total_byte_size <= MAX_ROW_GROUP_BYTES, 'row group exceeds 128MiB decoded-size guard; split the source row groups')
                    skip = metadata['row_offset'] if group_index == metadata['row_group'] else 0
                    group_offset = 0
                    for batch in parquet.iter_batches(batch_size=spec['batch_size'], row_groups=[group_index], use_threads=False):
                        if cancelled() or max_batches is not None and completed_batches >= max_batches:
                            metadata = {**metadata, 'status': 'paused'}; _commit(db, metadata); return metadata
                        if group_offset + batch.num_rows <= skip: group_offset += batch.num_rows; continue
                        raw_rows = batch.slice(max(0, skip - group_offset)).to_pylist()
                        group_offset += batch.num_rows
                        pieces = []; offset = metadata['output_bytes']; ordinal = metadata['rows']
                        db.execute('BEGIN IMMEDIATE')
                        for raw in raw_rows:
                            person = normalize(raw, spec['source']); line = (canonical(person.raw) + '\n').encode()
                            require(len(line) <= MAX_BATCH_BYTES, 'one row exceeds 8MiB import guard')
                            try:
                                db.execute('INSERT INTO people VALUES (?,?,?,?,?,?,?)', (person.uuid, ordinal, offset, len(line), raw.get('age'), raw.get('prefecture'), line.decode().casefold()))
                            except sqlite3.IntegrityError as error: raise ContractError(f'duplicate original UUID: {person.uuid}; import rejected') from error
                            pieces.append(line); offset += len(line); ordinal += 1
                            require(offset - metadata['output_bytes'] <= MAX_BATCH_BYTES, 'batch exceeds 8MiB; choose a smaller import batch')
                        require(shutil.disk_usage(directory).free >= 32 * 1024 ** 2, 'disk nearly full; import checkpoint retained')
                        stream.write(b''.join(pieces)); stream.flush(); os.fsync(stream.fileno())
                        for piece in pieces: checksum.update(piece)
                        group_done = group_offset == parquet.metadata.row_group(group_index).num_rows
                        next_metadata = {**metadata, 'rows': ordinal, 'row_group': group_index + 1 if group_done else group_index, 'row_offset': 0 if group_done else group_offset, 'output_bytes': offset, 'output_sha256': checksum.hexdigest()}
                        _commit(db, next_metadata); metadata = next_metadata; completed_batches += 1; progress(metadata)
            require(metadata['rows'] == metadata['total_rows'], 'Parquet ended before planned row count')
            if cancelled(): metadata = {**metadata, 'status': 'paused'}; _commit(db, metadata); return metadata
            metadata = {**metadata, 'phase': 'publishing'}; _commit(db, metadata)
            pack_id = _publish(root, directory, spec, metadata, db)
            metadata = {**metadata, 'status': 'completed', 'phase': 'completed', 'pack_id': pack_id}; _commit(db, metadata); progress(metadata)
            return metadata
        except Exception as error:
            db.rollback()
            stored = _load(db)
            if stored: _commit(db, {**stored, 'status': 'failed', 'error': str(error)[:1000]})
            raise
        finally: db.close()
