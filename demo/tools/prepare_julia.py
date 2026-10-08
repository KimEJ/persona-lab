"""Download a pinned official Julia runtime/checkpoint; no install or execution."""
import hashlib
import json
import urllib.parse
import urllib.request
from pathlib import Path

REVISION = "a85b127321d580d65176c89ced8273f305745d85"
MODEL_HASH = "df853bf7fe424420011f3d0c47a05d7341aa9eefa7fb9f203ea4aada4ad95b72"
root = Path(__file__).resolve().parents[1]
metadata_url = f'https://huggingface.co/api/models/SupersonicLabs/Julia-1/revision/{REVISION}?blobs=true'
with urllib.request.urlopen(metadata_url, timeout=30) as response:
    metadata_bytes = response.read(1048577)
assert len(metadata_bytes) <= 1048576, 'unexpected metadata size'
metadata = json.loads(metadata_bytes)
assert metadata['id'] == 'SupersonicLabs/Julia-1' and metadata['sha'] == REVISION
assert metadata.get('gated') is False and metadata['cardData']['license'] == 'apache-2.0'
files = [f for f in metadata['siblings'] if f['rfilename'] in {'README.md', 'pyproject.toml', 'config.json', 'julia_config.json', 'provenance.json', 'inference-policy.json', 'model.safetensors'} or f['rfilename'].startswith(('encoder/', 'tokenizer/')) or f['rfilename'].startswith('julia/') and f['rfilename'].endswith('.py') and '/tests/' not in f['rfilename']]
assert sum(f.get('size', 0) for f in files) < 620000000
destination = root / 'models/Julia-1'
manifest = {'source': 'SupersonicLabs/Julia-1', 'revision': REVISION, 'license': 'Apache-2.0', 'files': {}}
def checksums(path):
    sha256 = hashlib.sha256()
    git_sha1 = hashlib.sha1(b'blob ' + str(path.stat().st_size).encode() + b'\0')
    with path.open('rb') as handle:
        while chunk := handle.read(1024 * 1024):
            sha256.update(chunk); git_sha1.update(chunk)
    return sha256.hexdigest(), git_sha1.hexdigest()

for item in files:
    name = item['rfilename']
    assert not Path(name).is_absolute() and '..' not in Path(name).parts
    path = destination / name
    path.parent.mkdir(parents=True, exist_ok=True)
    expected = item.get('lfs', {}).get('sha256')
    existing_hashes = checksums(path) if path.exists() else (None, None)
    expected_blob = item.get('blobId')
    matches = existing_hashes[0] == expected if expected else expected_blob is not None and existing_hashes[1] == expected_blob
    if path.exists() and path.stat().st_size == item['size'] and matches:
        content_hash = existing_hashes[0]
    else:
        temporary = path.with_name(path.name + '.download')
        checksum = hashlib.sha256(); size = 0
        url = f'https://huggingface.co/SupersonicLabs/Julia-1/resolve/{REVISION}/' + urllib.parse.quote(name)
        with urllib.request.urlopen(url, timeout=180) as response, temporary.open('wb') as handle:
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                assert size <= item['size'], 'unexpected download size'
                handle.write(chunk); checksum.update(chunk)
        assert size == item['size'], 'incomplete file'
        content_hash = checksum.hexdigest()
        if expected: assert content_hash == expected, 'published checksum mismatch'
        else: assert expected_blob and checksums(temporary)[1] == expected_blob, 'published source blob mismatch'
        temporary.replace(path)
    manifest['files'][name] = {'sha256': content_hash, 'bytes': path.stat().st_size}
assert manifest['files']['model.safetensors']['sha256'] == MODEL_HASH
(root / 'verification/julia-download.json').write_text(json.dumps(manifest, indent=2) + '\n')
print(json.dumps({'status': 'verified', 'revision': REVISION, 'files': len(files), 'bytes': sum(f['bytes'] for f in manifest['files'].values())}))
