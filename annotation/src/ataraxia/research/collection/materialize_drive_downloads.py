"""Materialize authenticated Drive fetch references; signed URLs are never persisted."""
from ataraxia.runtime.config import project_root
import argparse
import hashlib
import json
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = project_root()
DESTINATION = ROOT / 'data/youtube_shorts_drive'


def download(item):
    name = item['name']
    if Path(name).name != name or '/' in name or '\\' in name:
        raise ValueError('Unsafe source filename')
    path = DESTINATION / item.get('subdirectory', 'videos') / name
    if not path.resolve().is_relative_to(DESTINATION.resolve()):
        raise ValueError('Destination escapes download directory')
    path.parent.mkdir(parents=True, exist_ok=True)
    expected = int(item['size'])
    if path.exists():
        if path.stat().st_size != expected:
            raise ValueError('Existing destination differs: ' + name)
        return {'id': item['id'], 'name': name, 'path': str(path.relative_to(ROOT)), 'size': expected, 'status': 'already_present'}
    error = ''
    observed_size = None
    for attempt in range(3):
        temporary = path.with_suffix(path.suffix + '.part')
        try:
            digest = hashlib.sha256()
            size = 0
            request = urllib.request.Request(item['url'], headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(request, timeout=180) as response, temporary.open('wb') as handle:
                for block in iter(lambda: response.read(1024 * 1024), b''):
                    handle.write(block)
                    size += len(block)
                    digest.update(block)
            if size != expected:
                observed_size = size
                raise ValueError(f'Expected {expected} bytes, downloaded {size}')
            temporary.replace(path)
            return {'id': item['id'], 'name': name, 'path': str(path.relative_to(ROOT)), 'size': size,
                    'sha256': digest.hexdigest(), 'status': 'downloaded'}
        except Exception as exc:
            error = type(exc).__name__  # Do not log signed URL-bearing exception messages.
            temporary.unlink(missing_ok=True)
            time.sleep(attempt + 1)
    return {'id': item['id'], 'name': name, 'status': 'failed', 'error_type': error,
            'expected_size': expected, 'observed_size': observed_size}


def main():
    items = json.load(sys.stdin)
    DESTINATION.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(download, items))
    with (DESTINATION / 'download_status.jsonl').open('a', encoding='utf-8') as handle:
        for result in results:
            handle.write(json.dumps(result) + '\n')
    print(json.dumps(results))
    if any(result['status'] == 'failed' for result in results):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
