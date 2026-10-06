"""Read the disk-backed import index; preview pages do not rescan the panel."""
import json
import sqlite3
from pathlib import Path
from .adapter import normalize
from .contracts import require


def catalog_path(root, source):
    base = (Path(root) / 'data/packs').resolve()
    path = (base / source['catalog_file']).resolve()
    require(path.parent == base and path.is_file() and path.suffix == '.sqlite', 'invalid catalog file')
    return path


def _read(stream, source, row):
    uuid, offset, length = row
    require(type(offset) is int and offset >= 0 and type(length) is int and 0 < length <= 8 * 1024 * 1024, 'invalid catalog record offset')
    stream.seek(offset); raw = json.loads(stream.read(length)); person = normalize(raw, source)
    require(person.uuid == uuid, 'catalog record UUID mismatch')
    return person


def indexed_page(root, source, data_path, panel, offset):
    clauses, params = [], []
    if panel.get('prefecture'): clauses.append('prefecture=?'); params.append(panel['prefecture'])
    if 'age_min' in panel: clauses.append('age>=?'); params.append(panel['age_min'])
    if 'age_max' in panel: clauses.append('age<=?'); params.append(panel['age_max'])
    if panel.get('query'): clauses.append('instr(rtrim(search_fold,char(10)),?)>0'); params.append(panel['query'].casefold())
    where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
    with sqlite3.connect(catalog_path(root, source)) as db, Path(data_path).open('rb') as stream:
        metadata = json.loads(db.execute('SELECT payload FROM metadata WHERE id=1').fetchone()[0])
        require(metadata['output_sha256'] == source['local_sha256'] and metadata['output_bytes'] == Path(data_path).stat().st_size, 'catalog/output snapshot mismatch')
        count = db.execute('SELECT COUNT(*) FROM people' + where, params).fetchone()[0]
        rows = db.execute('SELECT uuid,byte_offset,byte_length FROM people' + where + ' ORDER BY ordinal LIMIT 20 OFFSET ?', [*params, offset])
        people = [_read(stream, source, row) for row in rows]
    return people, count


def indexed_persona(root, source, data_path, uuid):
    with sqlite3.connect(catalog_path(root, source)) as db, Path(data_path).open('rb') as stream:
        row = db.execute('SELECT uuid,byte_offset,byte_length FROM people WHERE uuid=?', (uuid,)).fetchone()
        return _read(stream, source, row) if row else None
