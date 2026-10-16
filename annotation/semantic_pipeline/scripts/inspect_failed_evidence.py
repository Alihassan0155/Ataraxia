"""Read-only cached-response diagnostics; writes only its requested report file."""
from pathlib import Path
import argparse
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'src'))

from ataraxia.semantic.config import root_path
from ataraxia.semantic.storage import read, write, safe_id
from ataraxia.semantic.sources import annotations, metadata, bundle
from ataraxia.semantic.representation import parse, normalize_missing, response_errors, validate
from ataraxia.semantic.evidence import repair_quotes, EvidenceRepairError


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', required=True)
    parser.add_argument('--video-ids', nargs='+', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    root = root_path()
    run = root/'semantic_pipeline/runs'/safe_id(args.run)
    cfg = read(run/'frozen.json')['config']
    schema, taxonomy = read(run/'definitions/schema'), read(run/'definitions/taxonomy')
    rows, _ = annotations(root, cfg)
    meta = metadata(run)
    results = []
    for raw_id in args.video_ids:
        vid = safe_id(raw_id)
        job = bundle(root, cfg, vid, rows[vid], meta[vid])
        directory = run/'videos'/vid/job['source_fingerprint']
        paths = list((directory/'attempts').glob('*_repair.txt')) or list((directory/'attempts').glob('*_extraction.txt'))
        path = max(paths, key=lambda p:p.stat().st_mtime_ns)
        value, _ = normalize_missing(parse(path.read_text(encoding='utf-8-sig')), schema)
        issues = []
        try:
            value, changes = repair_quotes(value, schema, job['sources'])
        except EvidenceRepairError as exc:
            changes = []
            issues = exc.issues
        errors = response_errors(value, schema, taxonomy, job['sources'])
        try:
            validate(value, schema, taxonomy, job['sources'])
        except Exception as exc:
            errors.append(str(exc))
        results.append({'video_id':vid, 'response':path.relative_to(root).as_posix(),
                        'state':read(directory/'state.json'), 'quote_issues':issues,
                        'safe_quote_repairs':changes, 'remaining_errors':errors})
    write(Path(args.output), {'run':args.run, 'results':results})
    for result in results:
        print(result['video_id'], 'remaining issues:', len(result['remaining_errors']))


if __name__ == '__main__':
    main()
