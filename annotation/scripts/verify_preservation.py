"""Check original research hashes and media stats without inference or writes."""
import hashlib
import json
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    rows = json.loads((root/'research/migration/preserved_artifacts_before.json').read_text())
    errors = []
    for row in rows:
        path = root/row['path']
        if not path.is_file():
            errors.append({'path':row['path'], 'error':'missing'})
            continue
        stat = path.stat()
        if 'sha256' in row:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != row['sha256']:
                errors.append({'path':row['path'], 'error':'hash mismatch'})
        elif stat.st_size != row['bytes'] or stat.st_mtime_ns != row['mtime_ns']:
            errors.append({'path':row['path'], 'error':'media/opaque artifact stats changed'})
    result = {'checked':len(rows), 'errors':errors,
              'policy':'SHA-256 for text/evidence/configurations; size/mtime for untouched media and opaque files'}
    print(json.dumps(result,indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
