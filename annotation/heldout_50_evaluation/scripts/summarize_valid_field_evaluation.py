"""Add recorded-configuration audit and plain-language held-out conclusions.

Reads completed evaluation only; never changes selection rules or calibration.
"""
import argparse
import csv
import json
from pathlib import Path
from collections import Counter
from support import ROOT, read, write, validate_freeze, predictions, sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results-dir', type=Path,
                        default=ROOT/'reports/fieldwise_validation_20261011_v1')
    args = parser.parse_args()
    out = args.results_dir.resolve()
    cfg = validate_freeze()
    summary = read(out/'evaluation_summary.json')
    audits = {}
    for model in ('qwen', 'internvl', 'gemini'):
        rows = predictions(model, cfg)
        expected = cfg['models'][model]
        settings = expected.get('pilot_configuration', {})
        checks = {k: v for k,v in settings.items() if k not in ('video_ids', 'revision_requested')}
        checks['prompt_version'] = expected['prompt_version']
        mismatches, missing = [], []
        for vid, row in rows.items():
            meta = row['run_metadata']
            for key, value in checks.items():
                if key not in meta:
                    missing.append({'video_id':vid, 'field':key})
                elif meta[key] != value:
                    mismatches.append({'video_id':vid, 'field':key, 'expected':value, 'observed':meta[key]})
        audits[model] = {'n':len(rows), 'recorded_setting_mismatches':mismatches,
            'unlogged_setting_fields':dict(Counter(r['field'] for r in missing)),
            'unlogged_settings_per_video':missing,
            'note':'Absent metadata is a provenance gap, not proof of a setting deviation. '
                   'InternVL schema-repair change is covered by the preserved v3 amendment.'}
    write(out/'recorded_configuration_audit.json', audits)
    with (out/'paired_bootstrap_differences.csv').open() as f:
        differences = list(csv.DictReader(f))
    lines = ['# Held-out conclusion and configuration audit', '',
        'This conclusion is qualified: 50 valid three-human scalar references, 48 valid '
        'three-human distributions, and no valid Ali declared dominant labels. No invalid '
        'human scores or missing labels have been filled. It is not a complete 50-video '
        'categorical/distribution validation.', '',
        'Raw ranking: '+' > '.join(summary['raw_ranking'])+'.',
        'Frozen-calibrated ranking: '+' > '.join(summary['frozen_calibrated_ranking'])+'.',
        '**Recommended research pair: InternVL + Gemini.** The pair is unchanged from '
        'development; the weighted ranking orders InternVL first. The ranking does not '
        'establish an unqualified overall superiority over Gemini.', '',
        '## Calibration generalization', '',
        'Frozen pilot calibration reduced Qwen valence/recovery MAE and distribution TV; '
        'InternVL all three scalar MAEs and distribution TV; and Gemini recovery MAE. '
        'Their paired 95% error-difference intervals exclude zero in the improving '
        'direction on the eligible held-out fields. Qwen arousal and Gemini '
        'valence/arousal/emotions retain raw methods and are unchanged. No method was '
        'refitted or chosen using held-out labels.', '',
        'Use the already frozen per-field calibration and preserve raw values separately. '
        'These results validate alignment to three human perceptions; they do not '
        'establish calibrated probabilities of correctness.', '',
        '## Pairwise uncertainty', '']
    for r in differences:
        if r['first_variant'] == r['second_variant'] == 'calibrated' and r['metric'] == 'scalar_plus_tv_composite':
            lines.append(f'- {r["first_model"]} − {r["second_model"]}: '
                f'{float(r["difference_first_minus_second"]):.4f}, 95% CI '
                f'[{float(r["ci_lower"]):.4f}, {float(r["ci_upper"]):.4f}]; '
                f'zero-crossing/inconclusive: {r["interval_includes_zero"]}.')
    lines += ['', 'InternVL has lower calibrated valence MAE than Gemini; Gemini has lower '
        'distribution TV/JSD. Their arousal and recovery MAE differences are inconclusive. '
        'Qwen vs InternVL valence/recovery differences are inconclusive, but Qwen has '
        'higher arousal error and distribution TV. Refer to all metric intervals, rather '
        'than reading a single weighted rank as a significance test.', '',
        '## Runtime and provenance', '',
        'Summed saved successful inference times: Gemini 0.92 h; Qwen 4.32 h; InternVL '
        '9.76 h. These omit loading and may omit failed attempts/retries. Runtime is '
        'secondary to quality and does not enter the frozen ranking.', '',
        'Configuration metadata checks are exported in recorded_configuration_audit.json. '
        'Missing per-video fields cannot be inferred from the current config file. '
        'Amended repair/timeouts/key rotation and historical Gemini default/provider '
        'revision gaps remain disclosed. No prompt, calibration, threshold or ranking '
        'weight was altered.', '', '## Readiness', '',
        'The nominal pair is supported by the available held-out evidence, but the '
        'pipeline is not ready for an unconditional full-dataset freeze: finish Ali '
        'human-field corrections, resolve/document provider reproducibility gaps, and '
        'version the deployment policy. Do not tune on these test labels. No full-dataset '
        'annotation was started.', '',
        '[Detailed metrics, human agreement and confidence intervals](final_heldout_report.md).', '',
        'Reproduce this addendum:', '', '```powershell',
        '.\\.venv-qwen-cuda\\Scripts\\python.exe '
        'heldout_50_evaluation/scripts/summarize_valid_field_evaluation.py', '```']
    (out/'conclusion_and_configuration_audit.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    write(out/'addendum_provenance.json', {'script_sha256':sha(Path(__file__)),
        'source_summary_sha256':sha(out/'evaluation_summary.json'),
        'source_difference_csv_sha256':sha(out/'paired_bootstrap_differences.csv'),
        'calibration_modified':False})
    print(json.dumps({m:{'mismatches':a['recorded_setting_mismatches'],
          'unlogged_fields':a['unlogged_setting_fields']} for m,a in audits.items()},indent=2))


if __name__ == '__main__':
    main()
