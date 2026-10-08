"""100k explicit synthetic Parquet rows: bounded ingestion, resume, no model."""
import json
import resource
import sys
import time
import tracemalloc
from datetime import datetime, timezone
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq
from persona_lab.adapter import EXPECTED_FIELDS, NARRATIVE_FIELDS
from persona_lab.catalog import indexed_page
from persona_lab.parquet_import import create_import, run_import

root = Path(__file__).resolve().parents[1]
proof = root / 'runs/parquet-large-proof'; proof.mkdir(parents=True, exist_ok=True)
path = proof / 'explicit-synthetic-100k.parquet'
count = 100000
fields = [field for field in EXPECTED_FIELDS if field != 'travel_persona']
schema = pa.schema([(field, pa.int64() if field == 'age' else pa.string()) for field in fields])

def raw_row(i):
    raw = {field: 'explicit synthetic fixture' for field in fields}
    for field in NARRATIVE_FIELDS:
        if field in raw: raw[field] = 'これはプロジェクトが明示的に作った合成テストの記述です。' * 4
    raw.update(uuid=f'explicit-large-fixture-{i:08}', age=20+i%60, prefecture='東京都' if i%2==0 else '大阪府', country='日本', sports_persona=None if i%7==0 else raw['sports_persona'], arts_persona='' if i%11==0 else raw['arts_persona'])
    if i%37==0: raw['persona'] += ' literal_needle_%'
    return raw

# Writer also holds only a bounded row group, not the complete fake panel.
with pq.ParquetWriter(path, schema, compression='snappy') as writer:
    for first in range(0,count,1024):
        writer.write_table(pa.Table.from_pylist([raw_row(i) for i in range(first,min(first+1024,count))],schema=schema),row_group_size=1024)
source={'schema_version':'0.1','source_id':'persona-lab/explicit-large-parquet-fixture','version':'explicit-large-v1','url':'local:project-authored-synthetic-proof','license_id':'LicenseRef-Project-Fixture','license_url':'docs/DATA_SOURCES.md#synthetic-fixture','origin':'project_synthetic_fixture','name':'Explicit synthetic 100k Parquet proof','attribution':'Persona Lab project-authored synthetic test; not NVIDIA data'}
resume_root=proof/'resumed';baseline_root=proof/'baseline'
identifier=create_import(resume_root,local_path=path,source=source,batch_size=256)
paused=run_import(resume_root,identifier,max_batches=3)
assert paused['status']=='paused' and paused['rows']==768
last=0
native_peak=0
started=time.monotonic();tracemalloc.start()
def progress(status):
    global last,native_peak
    native_peak=max(native_peak,pa.total_allocated_bytes())
    if status['rows']-last>=20000:
        last=status['rows'];print(json.dumps({'stage':'synthetic_resume','rows':last,'total':count}),flush=True)
done=run_import(resume_root,identifier,progress=progress)
_,python_peak=tracemalloc.get_traced_memory();tracemalloc.stop()
elapsed=time.monotonic()-started
baseline_id=create_import(baseline_root,local_path=path,source=source,batch_size=256)
other=run_import(baseline_root,baseline_id)
resumed_manifest=json.loads((resume_root/'data/packs'/f'{done["pack_id"]}.json').read_text());baseline_manifest=json.loads((baseline_root/'data/packs'/f'{other["pack_id"]}.json').read_text())
assert resumed_manifest['local_sha256']==baseline_manifest['local_sha256'] and done['rows']==count
people,matched=indexed_page(resume_root,resumed_manifest,resume_root/'data/packs'/resumed_manifest['data_file'],{'selection':'all'},99980)
assert matched==count and len(people)==20 and people[-1].raw==raw_row(99999)
assert people[0].missing['travel_persona']=='absent'
_,filtered=indexed_page(resume_root,resumed_manifest,resume_root/'data/packs'/resumed_manifest['data_file'],{'selection':'filter','query':'literal_needle_%','age_min':50},0)
assert filtered==sum(i%37==0 and 20+i%60>=50 for i in range(count))
rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/(1024**2 if sys.platform=='darwin' else 1024)
assert python_peak<32*1024**2,python_peak
assert native_peak<128*1024**2,native_peak
assert rss<256,rss
receipt={'verified_at':datetime.now(timezone.utc).isoformat(),'scope':'Explicit project-authored 100000-row Parquet import only; not NVIDIA or model performance','rows':count,'parquet_row_group_rows':1024,'import_batch_rows':256,'paused_rows':paused['rows'],'resumed_equals_uninterrupted_sha256':True,'selected_tail_page':20,'filter_count':filtered,'python_tracemalloc_peak_mib':python_peak/1024**2,'observed_arrow_allocated_peak_mib':native_peak/1024**2,'process_peak_rss_mib':rss,'asserted_bounds_mib':{'python':32,'arrow_observed':128,'process_rss':256},'traced_resume_elapsed_seconds':elapsed,'limits':['Bounds passed for this controlled fixture; not a memory guarantee for arbitrary Parquet encodings.','Native decoded row-group guard128MiB and emitted batch guard8MiB are separate from reader overhead.','No inference or population accuracy measurement is performed.']}
(root/'verification/parquet-large-fixture.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n');print(json.dumps(receipt),flush=True)
