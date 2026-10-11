"""Restore pre-refactor entry-point files from exact snapshots; leave new modules.

Dry run by default. --apply restores only the 45 files listed in the migration
manifest. It does not delete packages, datasets, annotations, reports or Git history.
"""
import argparse
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    rows = json.loads((root/'research/migration/source_migration.json').read_text())
    for row in rows:
        target = (root/row['old']).resolve()
        snapshot = (root/row['snapshot']).resolve()
        if root not in target.parents or root not in snapshot.parents:
            raise ValueError('Unsafe migration manifest path')
        original = snapshot.read_bytes()
        if hashlib.sha256(original).hexdigest() != row['original_sha256']:
            raise ValueError('Source snapshot changed')
        if args.apply:
            target.write_bytes(original)
    print(f'{"Restored" if args.apply else "Would restore"} {len(rows)} original source files; no artifacts deleted.')


if __name__ == '__main__':
    main()
