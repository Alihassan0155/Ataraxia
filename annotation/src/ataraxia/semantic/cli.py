"""Explicit user-run commands. Status/control commands never load models."""
import argparse
import json
from pathlib import Path

from .config import root_path
from .storage import read, write, lock, safe_id, rebuild_manifest, complete_record, validate_array


def show_progress(root, config_path, run):
    """Read current sources and verified completions without loading GPU models."""
    from .worker import Worker
    from .sources import annotations, metadata
    frozen_path = run/'frozen.json'
    worker = Worker(root, config_path, run)
    worker.frozen = read(frozen_path) if frozen_path.exists() else {'config':read(config_path)}
    worker.cfg = worker.frozen['config']
    if frozen_path.exists():
        worker.metadata = metadata(run)
    else:
        import csv
        from ataraxia.runtime.config import resolve_path
        with resolve_path(root, worker.cfg['metadata_csv']).open(encoding='utf-8-sig', newline='') as f:
            worker.metadata = {row['assigned_id']:row for row in csv.DictReader(f)}
    rows, errors = annotations(root, worker.cfg)
    eligible = {vid:value for vid,value in rows.items() if vid in worker.metadata}
    if frozen_path.exists():
        pending, completed, failures, invalid = worker.queue(eligible)
        done, failed = len(completed), len(failures)
    else:
        done, failed, invalid = 0, 0, []
    total = len(eligible)
    print(f'Gemini available={total}; semantic done={done}; remaining={total-done}; '
          f'failed/backoff={failed}; invalid={len(invalid)}; '
          f'awaiting Gemini={len(set(worker.metadata)-set(eligible))}; source errors={len(errors)}', flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('run', 'status', 'inspect', 'download',
                        'pause', 'resume', 'stop', 'retry-failed', 'rebuild-manifest', 'retry-cached'))
    parser.add_argument('--run', default='semantic_v1')
    parser.add_argument('--config', default='semantic_pipeline/configs/pipeline.json')
    parser.add_argument('--video-id')
    parser.add_argument('--video-ids', nargs='+')
    parser.add_argument('--source-run')
    parser.add_argument('--selection-run', help='Reuse an existing selector response without another Qwen call')
    parser.add_argument('--models', nargs='+', choices=('extractor', 'embedder'),
                        default=['extractor', 'embedder'], help='Explicit download scope only')
    parser.add_argument('--once', action='store_true', help='Drain currently eligible work, then exit')
    args = parser.parse_args(argv)
    root = root_path()
    run = root/'semantic_pipeline/runs'/safe_id(args.run)
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = root/config_path
    if args.command == 'download':
        # Explicit opt-in only. Does not initialize a run or perform inference.
        from huggingface_hub import snapshot_download
        from ataraxia.runtime.config import resolve_path
        import re
        cfg = read(config_path)
        for name in args.models:
            model = cfg[name]
            if not re.fullmatch('[0-9a-f]{40}', model['revision']):
                raise ValueError('Download requires immutable model revisions')
            snapshot_download(model['checkpoint'], revision=model['revision'],
                              cache_dir=resolve_path(root, cfg['cache_dir']),
                              allow_patterns=['*.json', '*.safetensors', '*.bin', '*.txt', '*.model', '*.jinja'])
        return
    if args.command == 'run':
        show_progress(root, config_path, run)
        from .worker import Worker
        Worker(root, config_path, run).run_loop(once=args.once)
        return
    if args.command == 'retry-cached':
        if not args.source_run or not args.video_ids:
            parser.error('retry-cached requires --source-run and --video-ids')
        from .retry import retry_cached
        source_run = root/'semantic_pipeline/runs'/safe_id(args.source_run)
        selection_run = root/'semantic_pipeline/runs'/safe_id(args.selection_run) if args.selection_run else None
        result = retry_cached(root, config_path, run, source_run, args.video_ids, selection_run)
        print(json.dumps(result, indent=2))
        if not all(item['embedding_complete'] for item in result['results']):
            raise SystemExit(1)
        return
    if not (run/'frozen.json').exists():
        raise ValueError(f'Run not initialized: {run}. Start it with run first.')
    if args.command in ('pause', 'stop', 'retry-failed'):
        marker = {'pause':'PAUSE', 'stop':'STOP', 'retry-failed':'RETRY_FAILED'}[args.command]
        write(run/marker, {'requested_by':'interactive CLI'})
        print(f'{marker} requested; worker applies it between bounded batches.')
        return
    if args.command == 'resume':
        (run/'PAUSE').unlink(missing_ok=True)
        (run/'STOP').unlink(missing_ok=True)
        print('Pause/stop markers cleared. If the worker exited, issue run with the SAME config/run.')
        return
    if args.command == 'status':
        status = run/'reports/status.json'
        print(json.dumps(read(status) if status.exists() else {'status':'initialized; no poll yet'}, indent=2))
        print(f'Progress snapshot is not a liveness check. Events: {run / "logs/events.jsonl"}')
        return
    frozen = read(run/'frozen.json')
    if args.command == 'rebuild-manifest':
        with lock(run/'worker.lock'):
            records, errors = rebuild_manifest(run, frozen)
        print(json.dumps({'verified_versions':len(records), 'errors':errors}, indent=2))
        return
    if not args.video_id:
        parser.error('inspect requires --video-id')
    vid = safe_id(args.video_id)
    paths = list((run/'videos'/vid).glob('*/record.json'))
    records = [(complete_record(run, p, frozen), p) for p in paths]
    if not records:
        raise ValueError(f'No valid completed record for {vid}')
    record, path = max(records, key=lambda pair:pair[0]['completed_at'])
    vector = validate_array(run/record['embedding']['path'], record['embedding']['dimensions'],
                            frozen['config']['embedder']['normalization_tolerance'])
    print(json.dumps(record, indent=2, ensure_ascii=False))
    print(f'Record: {path}\nShape={vector.shape}, dtype={vector.dtype}, norm={float((vector@vector)**0.5):.8f}')


if __name__ == '__main__':
    main()
