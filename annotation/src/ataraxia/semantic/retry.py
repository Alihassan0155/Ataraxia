"""Explicit ID-scoped replay of historical failures into a NEW frozen run."""
from pathlib import Path
from ataraxia.runtime.config import resolve_path
from .config import freeze, check_freeze
from .worker import Worker, utc
from .sources import annotations, metadata, bundle
from .storage import read, write, lock, safe_id, sha, complete_record, rebuild_manifest


def retry_cached(root, config_path, run, source_run, video_ids, selection_run=None):
    if run == source_run or (run/'frozen.json').exists():
        raise ValueError('Targeted repair requires a NEW run; never overwrite an existing run')
    ids = [safe_id(v) for v in video_ids]
    if not ids or len(ids) != len(set(ids)):
        raise ValueError('Supply a nonempty list of unique video IDs')
    worker = Worker(root, config_path, run)
    summary = {'source_run':source_run.name, 'target_run':run.name, 'requested_ids':ids,
               'started_at':utc(), 'results':[], 'inference_scope':'requested IDs only; cached drafts first'}
    with lock(run/'worker.lock'):
        worker.frozen = freeze(root, config_path, run)
        worker.cfg = worker.frozen['config']
        worker.cache = resolve_path(root, worker.cfg['cache_dir'])
        worker.taxonomy = read(run/'definitions/taxonomy')
        worker.template = read(run/'definitions/template')
        worker.schema = read(run/'definitions/schema')
        worker.prompt = (run/'definitions/prompt').read_text(encoding='utf-8-sig')
        worker.metadata = metadata(run)
        rows, source_errors = annotations(root, worker.cfg)
        summary['source_errors'] = source_errors
        jobs, drafts, selections = [], {}, {}
        for vid in ids:
            if vid not in rows or vid not in worker.metadata:
                raise ValueError(f'{vid}: missing valid Gemini annotation or metadata')
            job = bundle(root, worker.cfg, vid, rows[vid], worker.metadata[vid])
            job['annotation'] = rows[vid]['annotation']
            old = source_run/'videos'/vid/job['source_fingerprint']
            if not old.is_dir():
                raise ValueError(f'{vid}: historical source hashes differ; cannot reuse cached draft')
            if (old/'record.json').exists():
                raise ValueError(f'{vid}: source run already has a completion record; this command handles failures only')
            candidates = list((old/'attempts').glob('*_extraction.txt'))+list((old/'attempts').glob('*_repair.txt'))
            if not candidates:
                raise ValueError(f'{vid}: no cached model output')
            path = max(candidates, key=lambda p:p.stat().st_mtime_ns)
            drafts[vid] = path.read_text(encoding='utf-8-sig')
            jobs.append(job)
            write(worker.directory(job)/'cached_provenance.json', {
                'path':path.relative_to(root).as_posix(), 'sha256':sha(path),
                'source_run_fingerprint':read(source_run/'frozen.json')['fingerprint']})
            if selection_run is not None:
                prior = selection_run/'videos'/vid/job['source_fingerprint']
                if read(prior/'cached_provenance.json')['sha256'] != sha(path):
                    raise ValueError(f'{vid}: selector was produced for a different cached draft')
                paths = list((prior/'attempts').glob('*_selector.txt'))
                if not paths:
                    raise ValueError(f'{vid}: no cached selector response')
                choice_path = max(paths, key=lambda p:p.stat().st_mtime_ns)
                selections[vid] = choice_path.read_text(encoding='utf-8-sig')
                write(worker.directory(job)/'cached_selector_provenance.json', {
                    'path':choice_path.relative_to(root).as_posix(), 'sha256':sha(choice_path)})
        try:
            with lock(resolve_path(root, worker.cfg['gpu_lock'])):
                for job in jobs:
                    write(worker.state_path(job), {'status':'processing', 'attempts':1, 'next_retry_at':0})
                worker.extract(jobs, cached_outputs=drafts, cached_selections=selections)
                check_freeze(root, config_path, run, worker.frozen)
                # Only successfully validated metadata gets embedded; no failed draft is published.
                worker.embed(jobs)
        except Exception as exc:
            summary['operational_error'] = f'{type(exc).__name__}: {exc}'
        finally:
            worker.unload()
            for job in jobs:
                path = worker.directory(job)/'record.json'
                metadata_pass = False
                error = worker.state(job).get('error')
                try:
                    metadata_pass = worker.recover_metadata(job) is not None
                    complete = path.exists() and bool(complete_record(run, path, worker.frozen))
                except Exception as exc:
                    complete = False
                    error = str(exc)
                summary['results'].append({'video_id':job['video_id'], 'semantic_validation_passed':metadata_pass,
                                           'embedding_complete':complete, 'error':error,
                                           'record':path.relative_to(run).as_posix() if complete else None})
            summary['finished_at'] = utc()
            write(run/'reports/targeted_retry.json', summary)
            rebuild_manifest(run, worker.frozen)
    return summary
