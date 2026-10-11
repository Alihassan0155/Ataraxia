"""Validate submitted held-out humans, then run the unchanged frozen evaluation.

Never guesses ID corrections, fills dominant labels, repairs human totals, or fits
calibration. The blank collection templates and frozen evaluation stay intact.
"""
import hashlib
import json
from collections import Counter
from pathlib import Path

from support import ROOT, validate_freeze, predictions, prediction_path, write
from build_three_human_reference import build, agreement
from build_human_soft_reference import write_csv
import evaluate as frozen_evaluation


def main():
    cfg = validate_freeze()
    sources = {
        'ali': ROOT.parent/'human_annotation/held_out/ali_annotation.json',
        'ghayas': ROOT.parent/'human_annotation/held_out/ghayas_annotation.csv',
        'zara': ROOT.parent/'human_annotation/held_out/zara_annotation.txt',
    }
    hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in [*sources.values(), *(prediction_path(m) for m in frozen_evaluation.MODELS),
                        ROOT/'config/pilot_calibration_and_selection.json']}
    refs, audits, _ = build(cfg['heldout_ids'], sources)
    # Use development cutpoints even for partial inspection; never held-out quantiles.
    low, medium = cfg['uncertainty_cutpoints']
    for row in refs:
        u = row['overall_human_uncertainty']
        row['uncertainty_bin'] = (None if u is None else
            'low' if u <= low+frozen_evaluation.EPS else
            'medium' if u <= medium+frozen_evaluation.EPS else 'high')
    model_audits = {}
    for model in frozen_evaluation.MODELS:
        path = prediction_path(model)
        rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
        counts = Counter(row.get('video_id') for row in rows)
        audit = {'row_count': len(rows),
                 'missing_ids': sorted(set(cfg['heldout_ids'])-set(counts)),
                 'unexpected_ids': sorted(set(counts)-set(cfg['heldout_ids'])),
                 'duplicate_ids': {k: v for k, v in counts.items() if v > 1}}
        try:
            valid = predictions(model, cfg)
            audit.update(validated_count=len(valid), validation_error=None)
        except Exception as exc:
            audit.update(validated_count=None, validation_error=str(exc))
        model_audits[model] = audit
    errors = [{'video_id': row['video_id'], 'annotator': h, 'field': field, 'error': error}
              for row in refs for h in sources
              for field, error in row[f'human_{h}_validation_errors'].items()]
    complete = (not errors and not any(a['issues'] or a['missing_ids'] or a['unexpected_ids']
                                     for a in audits.values())
                and all(a['validated_count'] == 50 for a in model_audits.values()))
    summary = {'status': 'ready' if complete else 'blocked_by_annotation_validation',
               'heldout_count': 50, 'original_pilot_id_overlap': [],
               'human_sources': {h: str(p) for h, p in sources.items()},
               'source_sha256': hashes, 'human_validation': audits,
               'model_validation': model_audits,
               'three_human_valid_scalar_counts': {
                   field: sum(row[field+'_human_mean'] is not None for row in refs)
                   for field in frozen_evaluation.FIELDS},
               'three_human_valid_distribution_count': sum(
                   row['pooled_emotion_distribution'] is not None for row in refs),
               'three_human_valid_declared_dominant_count': sum(
                   row['all_three_dominant_agree'] is not None for row in refs),
               'configuration_gaps': cfg['gaps'], 'calibration_refitted': False,
               'final_evaluation_performed': False, 'full_dataset_annotation_started': False}
    out = ROOT/'reports/submitted_validation'
    out.mkdir(parents=True, exist_ok=True)
    write(out/'input_validation.json', summary)
    write_csv(out/'invalid_human_fields.csv', errors)
    write(out/'partial_human_reference.json', {'final_reference': False, 'rows': refs})
    pairs, multi = agreement(refs)
    write_csv(out/'available_human_pairwise_agreement.csv', pairs)
    write(out/'available_human_agreement.json', {'pairwise': pairs, 'three_rater': multi,
          'qualification': 'Metric-specific valid subsets only; incomplete final validation.'})
    lines = ['# Submitted held-out annotation validation', '',
             f'Status: {summary["status"]}. Exactly 50 frozen IDs with zero original-pilot ID overlap.', '',
             'All original source files and frozen components remain unchanged. No IDs are guessed, '
             'human totals repaired, or missing dominant labels inferred. No calibration is fitted.', '',
             '## Human coverage', '',
             '| Annotator | Rows | Missing IDs | Unexpected IDs | Duplicate/malformed ID issues | Invalid affect fields |',
             '| --- | ---: | ---: | ---: | ---: | ---: |']
    for h, a in audits.items():
        lines.append(f'| {h} | {a["row_count"]} | {len(a["missing_ids"])} | '
                     f'{len(a["unexpected_ids"])} | '
                     f'{sum(i["kind"] in ("duplicate_id", "malformed_id") for i in a["issues"])} | '
                     f'{sum(e["annotator"] == h for e in errors)} |')
    lines += ['', 'Detailed ID lists and all field errors are in input_validation.json and '
              'invalid_human_fields.csv. Optional blank confidence scores are reported separately '
              'and do not block affect evaluation.', '',
              f'Valid three-human scalar counts: {summary["three_human_valid_scalar_counts"]}. '
              f'Valid distributions: {summary["three_human_valid_distribution_count"]}/50. '
              f'Valid three-human declared dominant labels: {summary["three_human_valid_declared_dominant_count"]}/50.', '',
              '## Models', '', *[f'- {m}: {a["validated_count"]}/50 validated predictions; '
                  f'missing={a["missing_ids"]}, unexpected={a["unexpected_ids"]}, '
                  f'duplicates={a["duplicate_ids"]}, error={a["validation_error"]}.' for m,a in model_audits.items()], '',
              '## Final evaluation gate', '',
              'Complete final ranking, calibration comparison, confidence intervals and model-pair '
              'selection wait for complete valid human annotations. Available pairwise human '
              'agreement and partial references are labeled as incomplete. No final ranking is claimed.', '',
              'Rerun `..\\..\\.venv-qwen-cuda\\Scripts\\python.exe scripts\\evaluate_submitted.py` '
              'from heldout_50_evaluation, or use the root command below:', '',
              '```powershell', '.\\.venv-qwen-cuda\\Scripts\\python.exe '
              'heldout_50_evaluation/scripts/evaluate_submitted.py', '```']
    (out/'validation_report.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == digest for p,digest in hashes.items())
    if not complete:
        print(json.dumps({k:summary[k] for k in ['status', 'three_human_valid_scalar_counts',
            'three_human_valid_distribution_count', 'three_human_valid_declared_dominant_count']}, indent=2))
        print('Final evaluation blocked; see reports/submitted_validation/validation_report.md.')
        raise SystemExit(2)
    # Change only source routing in memory; reuse all frozen metrics/calibration/weights.
    original_build = frozen_evaluation.build
    try:
        frozen_evaluation.build = lambda expected, ignored: build(expected, sources)
        frozen_evaluation.main()
    finally:
        frozen_evaluation.build = original_build
    assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == digest for p,digest in hashes.items())


if __name__ == '__main__':
    main()
