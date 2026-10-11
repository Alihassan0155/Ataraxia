"""Apply frozen held-out evaluation to valid fields without inventing labels.

Missing/invalid references affect only their metric. Joint ranking uses complete
three-human scalar/distribution references, matching the development protocol.
No calibrator is fitted, no selection threshold is changed, and no inference runs.
"""
import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

import numpy as np
import evaluate as frozen
from support import ROOT, read, write, validate_freeze, predictions, prediction_path, sha
from build_three_human_reference import build, agreement
from build_human_soft_reference import write_csv


def valid_field_metrics(x, p, y, q, dom, ref_doms, pooled_sets):
    result = {}
    for j, field in enumerate(frozen.FIELDS):
        valid = np.isfinite(y[:, j])
        metrics = (frozen.scalar_metrics(x[valid, j], y[valid, j]) if valid.any()
                   else dict.fromkeys(('signed_bias', 'mae', 'rmse', 'pearson', 'spearman')))
        result.update({field+'_'+key: value for key, value in metrics.items()})
    distributions = np.isfinite(q).all(axis=1)
    distances = frozen.emotion_distances(p[distributions], q[distributions]) if distributions.any() else None
    result['emotion_tv'] = float(distances[:, 0].mean()) if distances is not None else None
    result['emotion_jsd'] = float(distances[:, 1].mean()) if distances is not None else None
    for human, target in ref_doms.items():
        matches = [a == b for a, b in zip(dom, target) if b is not None]
        result['dominant_agreement_'+human] = float(np.mean(matches)) if matches else None
    for tie_aware in (False, True):
        matches = [(a in target if tie_aware else a == target[0])
                   for a, target in zip(dom, pooled_sets) if target]
        key = 'dominant_agreement_pooled'+('_tie_aware' if tie_aware else '')
        result[key] = float(np.mean(matches)) if matches else None
    joint = np.isfinite(y).all(axis=1) & distributions
    result['scalar_plus_tv_composite'] = (float(np.mean(np.column_stack((
        abs(x[joint]-y[joint])/frozen.RANGES,
        frozen.emotion_distances(p[joint], q[joint])[:, 0])))) if joint.any() else None)
    return result


def fmt(value):
    return f'{value:.3f}' if value is not None and math.isfinite(value) else 'unavailable'


def table(lines, columns, rows):
    lines.extend(['| '+' | '.join(columns)+' |', '| '+' | '.join(['---']*len(columns))+' |'])
    lines.extend('| '+' | '.join(map(str, row))+' |' for row in rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path,
                        default=ROOT/'reports/fieldwise_validation_20261011_v1')
    args = parser.parse_args()
    out = args.output_dir.resolve()
    if ROOT not in out.parents or out.exists():
        raise ValueError('Choose a new output folder inside heldout_50_evaluation; previous reports are preserved.')
    cfg = validate_freeze()
    sources = {h: ROOT.parent/'human_annotation/held_out'/name for h, name in (
        ('ali', 'ali_annotation.json'), ('ghayas', 'ghayas_annotation.csv'), ('zara', 'zara_annotation.txt'))}
    inputs = [*sources.values(), *(prediction_path(m) for m in frozen.MODELS),
              ROOT/'config/frozen_config.json', ROOT/'config/pilot_calibration_and_selection.json',
              ROOT/'config/freeze_manifest.json']
    hashes = {str(p): sha(p) for p in inputs}
    refs, human_audits, _ = build(cfg['heldout_ids'], sources)
    if any(a['missing_ids'] or a['unexpected_ids'] or a['issues'] for a in human_audits.values()):
        raise ValueError('Human ID alignment failed; correct verified IDs before evaluation.')
    records = {m: predictions(m, cfg) for m in frozen.MODELS}
    if any(set(r) != set(cfg['heldout_ids']) for r in records.values()):
        raise ValueError('Each model must have exactly 50 valid predictions.')
    selection = read(ROOT/'config/pilot_calibration_and_selection.json')
    calibration_hash = sha(ROOT/'config/pilot_calibration_and_selection.json')
    if calibration_hash != cfg['calibration_source_sha256']:
        raise ValueError('Frozen pilot calibration changed.')
    low, medium = cfg['uncertainty_cutpoints']
    for r in refs:
        u = r['overall_human_uncertainty']
        r['uncertainty_bin'] = (None if u is None else 'low' if u <= low+frozen.EPS
                               else 'medium' if u <= medium+frozen.EPS else 'high')
    ids = [r['video_id'] for r in refs]
    y = np.array([[r[f+'_human_mean_model_scale'] if r[f+'_human_mean_model_scale'] is not None
                   else np.nan for f in frozen.FIELDS] for r in refs])
    q = np.array([[r['pooled_emotion_distribution'][e] for e in frozen.EMOTIONS]
                  if r['pooled_emotion_distribution'] is not None else [np.nan]*8 for r in refs])
    labels = [r['uncertainty_bin'] for r in refs]
    ref_doms = {h: [r[f'human_{h}_dominant'] for r in refs] for h in frozen.HUMANS}
    pools = [r['pooled_distribution_dominant_set'] for r in refs]
    joint = np.where(np.isfinite(y).all(axis=1) & np.isfinite(q).all(axis=1))[0]
    coverage = {**{f: int(np.isfinite(y[:, j]).sum()) for j, f in enumerate(frozen.FIELDS)},
                'emotion_distribution': int(np.isfinite(q).all(axis=1).sum()),
                **{'dominant_'+h: sum(d is not None for d in ref_doms[h]) for h in frozen.HUMANS},
                'pooled_dominant': sum(bool(d) for d in pools), 'joint_ranking': len(joint)}
    out.mkdir(parents=True)
    snapshots = out/'source_snapshots'
    snapshots.mkdir()
    for h, path in sources.items():
        (snapshots/(h+path.suffix)).write_bytes(path.read_bytes())
    values, per_video, bias, runtime = {}, [], [], []
    corrected_output = {}
    name_map = {'qwen': 'Qwen', 'internvl': 'InternVL', 'gemini': 'Gemini'}
    for model in frozen.MODELS:
        model_rows = [records[model][vid] for vid in ids]
        x = np.array([[r[f] for f in frozen.FIELDS] for r in model_rows])
        p = np.array([[r['emotions'][e] for e in frozen.EMOTIONS] for r in model_rows])
        p = p/p.sum(axis=1)[:, None]
        plan = selection['calibration_plans'][name_map[model]]['calibration']
        cx, cp = frozen.calibration(x, p, plan)
        raw_dom = [r['dominant_emotion'] for r in model_rows]
        cal_dom = (raw_dom if plan['emotions']['method'] == 'raw'
                   else [frozen.maxima(dict(zip(frozen.EMOTIONS, row)))[0] for row in cp])
        corrected_output[model] = [{'video_id': vid, 'scalars': dict(zip(frozen.FIELDS, map(float, cx[i]))),
            'emotions': dict(zip(frozen.EMOTIONS, map(float, cp[i]))), 'dominant_emotion': cal_dom[i],
            'original_declared_dominant': raw_dom[i], 'pilot_calibration_sha256': calibration_hash}
            for i, vid in enumerate(ids)]
        for variant, xx, pp, dom in [('raw', x, p, raw_dom), ('calibrated', cx, cp, cal_dom)]:
            values[(model, variant)] = (xx, pp, y, q, dom, ref_doms, pools)
            for j, field in enumerate(frozen.FIELDS):
                valid = np.isfinite(y[:, j])
                bias.append({'model': model, 'variant': variant, 'field': field, 'n': int(valid.sum()),
                    'model_mean': float(xx[valid, j].mean()), 'human_mean': float(y[valid, j].mean()),
                    'signed_bias': float((xx[valid, j]-y[valid, j]).mean())})
            valid = np.isfinite(q).all(axis=1)
            for j, emotion in enumerate(frozen.EMOTIONS):
                bias.append({'model': model, 'variant': variant, 'field': emotion, 'n': int(valid.sum()),
                    'model_mean': float(pp[valid, j].mean()), 'human_mean': float(q[valid, j].mean()),
                    'signed_bias': float((pp[valid, j]-q[valid, j]).mean())})
            for i, vid in enumerate(ids):
                row = {'video_id': vid, 'model': model, 'variant': variant, 'uncertainty_bin': labels[i]}
                for j, field in enumerate(frozen.FIELDS):
                    row.update({field+'_prediction': float(xx[i, j]),
                        field+'_reference': float(y[i, j]) if np.isfinite(y[i, j]) else None,
                        field+'_signed_error': float(xx[i, j]-y[i, j]) if np.isfinite(y[i, j]) else None})
                ds = frozen.emotion_distances(pp[i:i+1], q[i:i+1])[0] if valid[i] else [None, None]
                row.update(emotion_tv=ds[0], emotion_jsd=ds[1], model_dominant=dom[i],
                           pooled_dominant=refs[i]['pooled_distribution_dominant'])
                for h in frozen.HUMANS:
                    row['dominant_agrees_'+h] = dom[i] == ref_doms[h][i] if ref_doms[h][i] is not None else None
                per_video.append(row)
        times = [r['run_metadata'].get('seconds') for r in model_rows]
        available = [float(t) for t in times if t is not None]
        runtime.append({'model': model, 'timing_n': len(available), 'sum_seconds': sum(available),
            'median_seconds': float(np.median(available)) if available else None,
            'max_seconds': max(available) if available else None,
            'normalized_records': sum(bool(r['run_metadata'].get('emotion_normalization', {}).get('applied')) for r in model_rows),
            'reliability_versions': dict(Counter(r['run_metadata'].get('reliability_policy_version', 'not_logged') for r in model_rows)),
            'repair_versions': dict(Counter(r['run_metadata'].get('repair_policy_version', 'not_logged') for r in model_rows)),
            'timing_limit': 'Saved successful per-video times; excludes model loading and may exclude failed attempts/key retries.'})
    write(out/'input_validation.json', {'humans': human_audits, 'models': {
        m: {'n': 50, 'missing_ids': [], 'unexpected_ids': [], 'duplicates': [],
            'schema_evidence_revision_checks': 'passed'} for m in frozen.MODELS}, 'metric_coverage': coverage})
    write(out/'human_soft_reference.json', {'rows': refs, 'coverage': coverage,
        'uncertainty_cutpoints': cfg['uncertainty_cutpoints'], 'cutpoints_source': 'original development pilot'})
    write_csv(out/'human_soft_reference.csv', refs)
    print('Validated 150 model predictions; computing 5,000 paired bootstrap resamples on valid fields...', flush=True)
    # The original bootstrap draws exactly the same 50 video indices for all models.
    # Only missing-field masking differs; no errors, thresholds or metrics are tuned.
    original_metric = frozen.metric_values
    try:
        frozen.metric_values = valid_field_metrics
        points, intervals, differences = frozen.bootstrap(values, cfg['bootstrap'])
    finally:
        frozen.metric_values = original_metric
    ranked = frozen.ranking({key: frozen.subset(data, joint) for key, data in values.items()},
                            [labels[i] for i in joint], cfg['ranking_weights'])
    stratified = []
    for (model, variant), data in values.items():
        for label in ('low', 'medium', 'high'):
            ix = np.where(np.array(labels, dtype=object) == label)[0]
            if len(ix):
                stratified.append({'model': model, 'variant': variant, 'uncertainty_bin': label,
                    'n': len(ix), **valid_field_metrics(*frozen.subset(data, ix))})
    pairs, multi = agreement(refs)
    order = {v: [r['model'] for r in sorted((r for r in ranked if r['variant'] == v), key=lambda r: r['rank'])]
             for v in ('raw', 'calibrated')}
    comparison = [r for r in differences if r['first_variant'] == r['second_variant'] == 'calibrated'
                  and r['metric'] == 'scalar_plus_tv_composite']
    changes = [r for r in differences if r['first_variant'] == 'calibrated' and r['second_variant'] == 'raw'
               and r['metric'] in ('valence_mae', 'arousal_mae', 'recovery_suitability_mae',
                                    'emotion_tv', 'emotion_jsd', 'scalar_plus_tv_composite')]
    ready = coverage['emotion_distribution'] == 50 and all(coverage['dominant_'+h] == 50 for h in frozen.HUMANS)
    summary = {'status': 'complete' if ready else 'qualified_evaluation_incomplete_human_fields',
        'coverage': coverage, 'raw_ranking': order['raw'], 'frozen_calibrated_ranking': order['calibrated'],
        'nominal_recommended_pair': order['calibrated'][:2], 'pair_status': 'qualified pending human corrections',
        'inconclusive_calibrated_pairs': [r for r in comparison if r['interval_includes_zero']],
        'ranking_weights': cfg['ranking_weights'], 'ranking_subset_n': len(joint),
        'calibration_changes': changes, 'bootstrap': cfg['bootstrap'], 'source_hashes': hashes,
        'evaluation_script_sha256': sha(Path(__file__)), 'calibration_refitted': False,
        'uncertainty_bins': dict(Counter(labels)), 'configuration_gaps': cfg['gaps'],
        'runtime': runtime, 'full_dataset_annotation_started': False, 'ready_for_full_dataset': False,
        'reference': 'Three independent human perceptions, not perfect ground truth.',
        'deviations': ['Field-specific exclusions for invalid human labels; no two-human fallback.',
            'Joint ranking uses complete three-human scalar/distribution subset, matching development convention.',
            'Ghayas nine IDs corrected with user authorization; original backup and correction mapping retained.',
            'Reliability amendments v2/v3/v4 changed timeout/key-failover and InternVL repair policy after failures.'],
        'frozen_calibration_methods': {m: {k: v['method'] for k,v in selection['calibration_plans'][name_map[m]]['calibration'].items()}
                                       for m in frozen.MODELS},
        'mean_human_uncertainty': {key: float(np.mean([r[key] for r in refs if r[key] is not None]))
            for key in ('valence_uncertainty', 'arousal_uncertainty', 'recovery_suitability_uncertainty', 'emotion_tv', 'emotion_jsd')}}
    for name, rows in [('raw_vs_calibrated_metrics.csv', [{'model': k[0], 'variant': k[1],
            'metric_sample_counts': coverage, **v} for k,v in points.items()]),
            ('metric_confidence_intervals.csv', intervals), ('paired_bootstrap_differences.csv', differences),
            ('uncertainty_stratified_metrics.csv', stratified), ('per_video_errors.csv', per_video),
            ('model_ranking.csv', ranked), ('human_pairwise_agreement.csv', pairs),
            ('model_bias_analysis.csv', bias), ('runtime_summary.csv', runtime)]:
        write_csv(out/name, rows)
    write(out/'calibrated_predictions.json', corrected_output)
    write(out/'evaluation_summary.json', summary)
    lines = ['# Held-out evaluation against three-human soft references', '',
        'This evaluates the untouched 50-video test selection using only frozen development '
        'calibration. Original predictions/human files remain unchanged. No fitting, threshold '
        'changes or inference occurred. The human reference represents perceptions, not truth.', '',
        '## Validation and eligible counts', '',
        f'All three models: 50 valid unique predictions, no missing/duplicate/unexpected IDs; '
        f'frozen checkpoint, evidence, prompt and media checks pass. All humans now have 50 aligned '
        f'unique IDs. All three scalars: 50 valid three-human references. Emotion distributions: '
        f'{coverage["emotion_distribution"]}/50. Ali declared dominant labels: '
        f'{coverage["dominant_ali"]}/50. Ghayas/Zara declared labels: 50/50 each.', '',
        'Ali emotion totals 11 (TT_7440201647755644182) and 14 (YT_WiBhWcqrhF0) remain invalid. '
        'All Ali declared dominant labels are blank. Four optional confidence values are absent. '
        'Invalid fields alone are excluded; missing categorical labels are not inferred or counted '
        'as disagreements. No two-human reference replaces a missing third value. Detailed errors '
        'are in input_validation.json. Ghayas ID corrections are backed up and documented.', '',
        '## Human agreement', '',
        'Human scalars are on [0,10]. Emotion scores must total 10 and are converted to probabilities. '
        'Reference means require three valid values per field. Uncertainty is the mean of three '
        'range-normalized mean pairwise scalar differences and mean pairwise emotion TV. '
        'Declared-label disagreement is separate. No held-out quantiles set thresholds.', '']
    table(lines, ['Pair', 'Field', 'N', 'MAE / TV', 'Pearson / agreement', 'Spearman / kappa'],
          [[r['pair'], r['field'], r['n'], fmt(r.get('mae', r.get('mean_tv'))),
            fmt(r.get('pearson', r.get('agreement'))), fmt(r.get('spearman', r.get('cohen_kappa')))] for r in pairs])
    lines += ['', f'Three-human declared-label agreement/Fleiss kappa: unavailable (N={multi["n"]}). '
              'Distribution-derived pooled maxima remain separate and preserve ties.', '',
              f'Frozen uncertainty cutpoints: {low:.6f}, {medium:.6f}; bins: {dict(Counter(labels))}. '
              'Invalid distributions yield unbinned rows while their scalar metrics remain eligible.', '',
              '## Raw and frozen-calibrated performance', '',
              'Valence is [-1,1]; arousal/recovery are [0,1]. Scalar N=50; distribution N=48. '
              'JSD is base-2 divergence. Signed bias is model minus human.', '']
    table(lines, ['Model', 'Variant', 'Field', 'MAE', 'RMSE', 'Pearson', 'Spearman', 'Bias'],
        [[m, v, f, *[fmt(points[(m,v)][f+'_'+metric]) for metric in
            ('mae', 'rmse', 'pearson', 'spearman', 'signed_bias')]]
            for m,v in points for f in frozen.FIELDS])
    lines += ['']
    table(lines, ['Model', 'Variant', 'TV', 'JSD', 'Dominant Ali', 'Dominant Ghayas', 'Dominant Zara', 'Pooled dominant'],
        [[m, v, *[fmt(points[(m,v)][k]) for k in ('emotion_tv', 'emotion_jsd', 'dominant_agreement_ali',
            'dominant_agreement_ghayas', 'dominant_agreement_zara', 'dominant_agreement_pooled')]] for m,v in points])
    lines += ['', 'Canonical pooled dominant agreement uses the frozen emotion-key tie rule; '
              'tie-aware agreement is also exported. Per-emotion model/human means and biases '
              'are in model_bias_analysis.csv.', '', '## Paired bootstrap confidence intervals', '',
              '5,000 paired video-level percentile resamples, frozen seed 20261009; identical '
              '50-video draws for every model/variant. Metric-specific invalid references are '
              'masked within each draw. Degenerate correlations are omitted with valid draw counts. '
              'Calibrators remain fixed. CIs exclude refitting, provider repetition, annotator '
              'population and model-selection uncertainty. No multiplicity adjustment; interpret '
              'intervals descriptively.', '']
    table(lines, ['Model', 'Variant', 'Metric', 'Estimate', '95% CI'],
        [[r['model'], r['variant'], r['metric'], fmt(r['estimate']),
          '['+fmt(r['ci_lower'])+', '+fmt(r['ci_upper'])+']'] for r in intervals
          if r['metric'] in ('valence_mae', 'arousal_mae', 'recovery_suitability_mae', 'emotion_tv')])
    lines += ['', 'Calibrated minus raw: negative error differences favor calibration. '
              'Intervals containing zero do not establish improvement or equivalence.', '']
    table(lines, ['Model', 'Metric', 'Calibrated − raw', '95% CI', 'Includes zero'],
        [[r['first_model'], r['metric'], fmt(r['difference_first_minus_second']),
          '['+fmt(r['ci_lower'])+', '+fmt(r['ci_upper'])+']', r['interval_includes_zero']] for r in changes])
    lines += ['', '## Human uncertainty strata', '']
    table(lines, ['Model', 'Variant', 'Bin', 'N', 'Valence MAE', 'Arousal MAE', 'Recovery MAE', 'TV', 'JSD'],
        [[r['model'], r['variant'], r['uncertainty_bin'], r['n'],
          *[fmt(r[k]) for k in ('valence_mae','arousal_mae','recovery_suitability_mae','emotion_tv','emotion_jsd')]]
          for r in stratified])
    lines += ['', '## Frozen quality ranking and pair recommendation', '',
        f'Joint ranking N={len(joint)} complete numeric/distribution references. Weights remain '
        '40% scalar alignment, 25% TV, 15% high-uncertainty error, 10% absolute normalized bias, '
        '10% worst normalized scalar MAE. Runtime is separate. No criterion was selected after '
        'viewing held-out errors.', '']
    table(lines, ['Variant', 'Rank', 'Model', 'Scalar alignment', 'TV', 'High-bin error', 'Abs bias', 'Worst scalar', 'Weighted rank'],
        [[r['variant'], r['rank'], r['model'], *[fmt(r[k]) for k in ('scalar_alignment_mean', 'emotion_tv',
          'high_uncertainty_composite', 'mean_absolute_scalar_bias', 'worst_scalar_normalized_mae', 'weighted_metric_rank')]]
          for r in sorted(ranked, key=lambda r:(r['variant'],r['rank']))])
    lines += ['', 'Paired calibrated model differences in shared scalar-plus-TV error '
        '(positive means first model is worse); this error metric is distinct from weighted metric rank.', '']
    table(lines, ['Comparison', 'Difference', '95% CI', 'Inconclusive'],
        [[r['first_model']+' − '+r['second_model'], fmt(r['difference_first_minus_second']),
          '['+fmt(r['ci_lower'])+', '+fmt(r['ci_upper'])+']', r['interval_includes_zero']] for r in comparison])
    lines += ['', 'Raw order: '+' > '.join(order['raw'])+'.',
        'Frozen-calibrated order: '+' > '.join(order['calibrated'])+'.',
        '**Nominal recommended pair: '+', '.join(summary['nominal_recommended_pair'])+'.** '
        'This is qualified by incomplete human fields, metric-specific intervals and the frozen '
        'deployment/provenance limitations. A weighted rank alone is not evidence of superiority; '
        'a zero-crossing difference is inconclusive, not equivalence. Final completeness requires '
        'Ali corrections. Do not tune calibration using this test.', '', '## Runtime', '']
    table(lines, ['Model', 'Timed videos', 'Sum hours', 'Median seconds', 'Normalized records'],
          [[r['model'], r['timing_n'], fmt(r['sum_seconds']/3600), fmt(r['median_seconds']), r['normalized_records']]
           for r in runtime])
    lines += ['', 'Saved successful inference times exclude loading and may exclude failed '
        'attempts/key retries; these are not total wall-clock costs.', '', '## Deviations and readiness', '',
        *['- '+g for g in [*cfg['gaps'], *summary['deviations']]], '',
        'Reliability amendment files v2/v3/v4 are preserved. InternVL normalization events '
        'retain original model scores; human invalid totals have not been normalized. '
        'Human independence is user-confirmed; blindness to model outputs is unverified. '
        'The balanced category/source selection is not a random sample proportional to the full '
        'dataset, so estimates should not be presented as full-population performance.', '',
        '**Not ready for an unconditional full-dataset release:** finish human corrections, '
        'resolve provider provenance gaps and version the deployment/application policy. '
        'The frozen calibration has been independently tested on all valid held-out fields. '
        'No full-dataset annotation started.', '', '## Reproduce', '', '```powershell',
        '.\\.venv-qwen-cuda\\Scripts\\python.exe heldout_50_evaluation/scripts/evaluate_valid_fields.py '
        '--output-dir heldout_50_evaluation/reports/<new-folder>', '```', '',
        'All source hashes, frozen parameters and complete metric tables are preserved in this '
        'folder. Choose a new output folder for any rerun; previous results stay unchanged.']
    (out/'final_heldout_report.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    assert all(sha(Path(p)) == digest for p,digest in hashes.items()), 'An original source changed during evaluation'
    validate_freeze()
    print(json.dumps({'output': str(out), 'coverage': coverage, 'raw': order['raw'],
        'calibrated': order['calibrated'], 'nominal_pair': summary['nominal_recommended_pair']}, indent=2))


if __name__ == '__main__':
    main()
