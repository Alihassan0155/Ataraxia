"""Read-only audit of frozen semantic artifacts; no model loading or inference.

Writes only to a new, explicitly selected report directory. Neighbors are a
review aid, not a retrieval benchmark or an entailment score.
"""
import argparse
import collections
import csv
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'src'))


def reason(error):
    if 'JSONDecodeError' in error:
        return 'malformed_or_truncated_json'
    if 'omitted asserted field' in error:
        return 'incomplete_repair_decisions'
    if 'EvidenceRepairError' in error or 'non-verbatim' in error:
        return 'unsupported_or_overlong_quote'
    if 'controlled vocabulary' in error or 'taxonomy' in error:
        return 'controlled_vocabulary'
    return 'other_validation'


def csv_write(path, rows, fields):
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def audit(run, output):
    import numpy as np
    from ataraxia.semantic.storage import read, complete_record
    from ataraxia.semantic.sources import annotations, metadata, bundle
    from ataraxia.semantic.representation import validate, render

    run = run.resolve()
    output = output.resolve()
    if output == run or run in output.parents:
        raise ValueError('Use a separate report directory outside the active run')
    frozen = read(run/'frozen.json')
    cfg = frozen['config']
    sources, source_errors = annotations(ROOT, cfg)
    manifest = metadata(run)
    schema, taxonomy, template = [read(run/'definitions'/key) for key in ('schema', 'taxonomy', 'template')]
    # Snapshot paths once. The live worker may finish more records after this point.
    paths = sorted((run/'videos').glob('*/*/record.json'))
    records, vectors, errors, flags = [], [], [], []
    missing = collections.Counter()
    for path in paths:
        try:
            record = complete_record(run, path, frozen)
            vid = record['video_id']
            job = bundle(ROOT, cfg, vid, sources[vid], manifest[vid])
            if job['source_fingerprint'] != record['source_fingerprint']:
                raise ValueError('Current source fingerprint differs from saved input')
            validate(record['semantic'], schema, taxonomy, job['sources'])
            description, text = render(record['semantic'], job, template)
            if description != record['semantic_description'] or text != (run/record['embedding_input_path']).read_text(encoding='utf-8'):
                raise ValueError('Rendered description/input differs from frozen template')
            vector = np.load(run/record['embedding']['path'], allow_pickle=False)
            records.append(record)
            vectors.append(vector)
            semantic = record['semantic']
            for field, value in semantic.items():
                if value is None or value == [] or value == 'unknown':
                    missing[field] += 1
            for item in semantic['field_evidence']:
                if item['source'] in ('caption', 'title', 'original_category'):
                    flags.append({'video_id':vid, 'field':item['field'], 'flag':'auxiliary_source_review',
                                  'value':json.dumps(semantic[item['field']], ensure_ascii=False),
                                  'source':item['source'], 'quote':item['quote']})
            if '\ufffd' in semantic['semantic_summary']:
                flags.append({'video_id':vid,'field':'semantic_summary','flag':'replacement_character_review',
                              'value':semantic['semantic_summary'],'source':'','quote':''})
        except Exception as exc:
            errors.append({'path':str(path), 'error':str(exc)})
    failures = []
    for path in sorted((run/'videos').glob('*/*/state.json')):
        state = read(path)
        if state.get('status') == 'failed':
            failures.append({'video_id':path.parent.parent.name,'attempts':state['attempts'],
                             'category':reason(state.get('error','')), 'error':state.get('error','')})
    neighbors = []
    if len(vectors) > 1:
        matrix = np.stack(vectors)
        similarity = matrix @ matrix.T
        np.fill_diagonal(similarity, -np.inf)
        for i, record in enumerate(records):
            for rank, j in enumerate(np.argsort(-similarity[i])[:min(3,len(records)-1)], 1):
                other = records[int(j)]
                neighbors.append({'video_id':record['video_id'], 'rank':rank, 'neighbor_id':other['video_id'],
                                  'cosine':float(similarity[i,j]),'summary':record['semantic']['semantic_summary'],
                                  'neighbor_summary':other['semantic']['semantic_summary'],
                                  'relevance_judgment':'', 'reviewer':'', 'notes':''})
    output.mkdir(parents=True, exist_ok=False)
    summary = {'run':str(run),'run_fingerprint':frozen['fingerprint'], 'snapshot_record_count':len(paths),
               'verified_completed':len(records),'artifact_errors':errors,'source_errors':source_errors,
               'repaired_records':sum(bool(r.get('extraction_repairs')) for r in records),
               'missing_field_counts':dict(missing),'failed_records':len(failures),
               'failure_categories':dict(collections.Counter(f['category'] for f in failures)),
               'exhausted_failures':sum(f['attempts']>=cfg['max_attempts'] for f in failures),
               'review_flags':len(flags),
               'duplicate_vectors':len(vectors)-len({v.tobytes() for v in vectors}),
               'limitations':['Structural validation does not establish semantic entailment.',
                             'Existing-video nearest neighbors are not a held-out text-query benchmark.',
                             'No raw-video viewing or human relevance judgments were performed.',
                             'Live input files may grow after this read-only snapshot.']}
    (output/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
    csv_write(output/'retrieval_review.csv',neighbors,['video_id','rank','neighbor_id','cosine','summary','neighbor_summary','relevance_judgment','reviewer','notes'])
    csv_write(output/'evidence_review.csv',flags,['video_id','field','flag','value','source','quote'])
    csv_write(output/'failures.csv',failures,['video_id','attempts','category','error'])
    report = ('# Semantic quality audit\n\n'
              f"Verified {len(records)}/{len(paths)} completed artifacts; {len(errors)} artifact errors.\n\n"
              f"{summary['repaired_records']} records required repair; {len(failures)} current failures, "
              f"{summary['exhausted_failures']} exhausted. Failure groups: {summary['failure_categories']}.\n\n"
              'Use retrieval_review.csv to label nearest-neighbor relevance as relevant/partial/unrelated. '
              'There is no automatic retrieval-quality pass. Evidence review flags are review prompts, '
              'not proven errors. Missing fields are not filled automatically.\n\n'
              '## Sparse fields\n\n' + '\n'.join(f'- {k}: {v}/{len(records)} empty' for k,v in missing.most_common()) +
              '\n\n## Limitations\n\n'+'\n'.join('- '+s for s in summary['limitations'])+'\n')
    (output/'report.md').write_text(report,encoding='utf-8')
    print(json.dumps(summary,indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.run):
        parser.error('Invalid run name')
    audit(ROOT/'semantic_pipeline/runs'/args.run, args.output)
