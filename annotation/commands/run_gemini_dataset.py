"""Prepare/resume remaining normalized videos using the existing Gemini backend."""
import argparse
import csv
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from ataraxia.runtime.config import Settings
from ataraxia.distributed.common import lock, sha, write, safe_id


def prepare(run):
    manifest = ROOT/'data/normalized/preprocessed_merged_v2/ready_metadata.csv'
    if (run/'configuration.json').exists():
        cfg = json.loads((run/'configuration.json').read_text())
        if cfg['manifest_sha256'] != sha(manifest):
            raise RuntimeError('Ready manifest changed; preserve this run and use a new run name')
        return cfg
    with manifest.open(encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    ids = [r['assigned_id'] for r in rows]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate ready IDs')
    completed = set()
    sources = []
    for base in (ROOT/'outputs', ROOT/'pilot_50_reels_30h', ROOT/'heldout_50_evaluation', ROOT/'runs'):
        for path in base.rglob('annotations.jsonl'):
            if 'gemini' not in str(path).lower() or run in path.parents:
                continue
            valid = set()
            for line in path.read_text(encoding='utf-8-sig').splitlines():
                try:
                    item = json.loads(line)
                    from ataraxia.annotation.common import VideoAnnotation
                    VideoAnnotation.model_validate(item)
                    valid.add(item['video_id'])
                except (ValueError, KeyError):
                    continue
            completed.update(valid)
            sources.append({'path':str(path), 'sha256':sha(path), 'valid_ids':sorted(valid)})
    protected = set()
    for path in (ROOT/'pilot_50_reels_30h/pilot_metadata.csv',
                 ROOT/'held out/merged_50/held_out_50.csv'):
        if not path.exists():
            raise FileNotFoundError(f'Required research split: {path}')
        with path.open(encoding='utf-8-sig', newline='') as f:
            for row in csv.DictReader(f):
                protected.add(row.get('assigned_id') or row.get('video_id'))
    selected = [r for r in rows if r['assigned_id'] not in completed | protected]
    if not selected:
        raise ValueError('No remaining eligible videos')
    # Validate ALL evidence before staging or making any API request.
    for row in selected:
        safe_id(row['assigned_id'])
        for key in ('file_path', 'context_path'):
            if not Path(row[key]).is_file():
                raise FileNotFoundError(f"{row['assigned_id']} {key}: {row[key]}")
    for kind in ('videos', 'context'):
        (run/'evidence'/kind).mkdir(parents=True, exist_ok=True)
    for row in selected:
        vid = row['assigned_id']
        source = Path(row['file_path'])
        target = run/'evidence/videos'/f'{vid}.mp4'
        if not target.exists():
            try:
                os.link(source, target)
            except OSError:
                shutil.copy2(source, target)
        context = run/'evidence/context'/f'{vid}.json'
        if not context.exists():
            shutil.copy2(row['context_path'], context)
    with (run/'metadata.csv').open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(selected[0]))
        writer.writeheader()
        writer.writerows(selected)
    frozen = ROOT/'heldout_50_evaluation/config/frozen_config.json'
    cfg = {'manifest':str(manifest), 'manifest_sha256':sha(manifest),
           'ready_total':len(rows), 'selected_count':len(selected),
           'excluded_completed_ids':sorted(set(ids) & completed),
           'excluded_research_ids':sorted(set(ids) & protected),
           'completed_sources':sources, 'selected_ids':[r['assigned_id'] for r in selected],
           'model':json.loads(frozen.read_text())['models']['gemini'],
           'frozen_config_sha256':sha(frozen), 'calibration':'none; raw predictions preserved'}
    write(run/'configuration.json', cfg)
    return cfg


def progress(run, cfg):
    """Use the backend's resume IDs, restricted to this frozen run's selection."""
    from ataraxia.annotation.common import load_processed_ids
    selected = set(cfg['selected_ids'])
    done = selected & load_processed_ids(run/'predictions/gemini/annotations.jsonl')
    return len(done), len(selected)-len(done)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'run'])
    parser.add_argument('--run', default='gemini_full_remaining_20261012')
    args = parser.parse_args()
    run = ROOT/'runs'/safe_id(args.run)
    run.mkdir(parents=True, exist_ok=True)
    with lock(run/'controller.lock'):
        cfg = prepare(run)
        done, remaining = progress(run, cfg)
        print(f"Ready={cfg['ready_total']}; selected={cfg['selected_count']}; "
              f"done={done}; remaining={remaining}; output={run}", flush=True)
        if args.action == 'prepare':
            return
        settings = Settings.load(ROOT)
        env = settings.child_environment()
        env.update(ATARAXIA_PILOT_DIR=str(run/'evidence'),
                   ATARAXIA_METADATA_PATH=str(run/'metadata.csv'),
                   ATARAXIA_OUTPUT_ROOT=str(run/'predictions'),
                   ATARAXIA_GEMINI_ALL_KEYS_BEFORE_STOP='1',
                   ATARAXIA_EXPECTED_VIDEO_COUNT=str(cfg['selected_count']))
        # Validate credentials without printing their contents.
        if not (env.get('GEMINI_API_KEYS', '').strip() or env.get('GEMINI_API_KEY', '').strip()):
            raise RuntimeError('Gemini API keys unavailable in the project .env/environment')
        os.environ.update(env)
        from ataraxia.annotation.backends import gemini
        if gemini.MODEL != cfg['model']['checkpoint']:
            raise RuntimeError('Backend model differs from frozen held-out checkpoint')
        code = subprocess.call([sys.executable, '-u', '-m',
                                'ataraxia.annotation.backends.gemini_execution'], env=env, cwd=ROOT)
        raise SystemExit(code)


if __name__ == '__main__':
    main()
