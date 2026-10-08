"""Explicit optional official Viewer fetch; keep existing local sample files."""
import json
import shutil
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'src'))
from persona_lab.adapter import read_personas
from persona_lab.contracts import require
from persona_lab.importer import fetch_sample

directory = root / 'data/packs'
manifest = directory / 'nemotron-japan-sample.json'
data = directory / 'nemotron-japan-sample.jsonl'
if manifest.exists() or data.exists():
    require(manifest.is_file() and data.is_file(), 'partial existing sample; preserve it and inspect before retrying')
    source = json.loads(manifest.read_text())
    rows = sum(1 for _ in read_personas(data, source))
    print(json.dumps({'status': 'existing local sample preserved', 'rows': rows}))
else:
    imported = fetch_sample(root)
    source = json.loads((directory / (imported['id'] + '.json')).read_text())
    shutil.copyfile(directory / source['data_file'], data)
    source.update(data_file=data.name, name='NVIDIA 일본 · 공개 소형 샘플')
    temporary = manifest.with_suffix('.tmp'); temporary.write_text(json.dumps(source, ensure_ascii=False, indent=2) + '\n'); temporary.replace(manifest)
    print(json.dumps({'status': 'official optional sample prepared', 'rows': source['record_count'], 'license': source['license_id']}))
