"""Local-only abstention review. Retains all raw checkpoints, never assigns a new category."""
from collections import Counter
import json
from pathlib import Path

from .category_completion import accept
from .run_category_completion import load_inputs,filler_only
from .__main__ import atomic_json


def finalize(prepared,run,decisions):
    requests,taxonomy,_=load_inputs(prepared);run=Path(run)
    if set(decisions)-{r['video_id'] for r in requests}:
        raise ValueError('Review contains an unapproved video ID')
    run_id=json.loads((run/'run.json').read_text(encoding='utf-8'))['run_id']
    if {p.parent.name for p in (run/'videos').glob('*/result.json')}!={r['video_id'] for r in requests}:
        raise ValueError('Checkpoint cohort differs from approved requests')
    out=run/'reviewed';out.mkdir(exist_ok=False)
    records=[]
    for request in requests:
        p=run/'videos'/request['video_id']/'result.json'
        r=json.loads(p.read_text(encoding='utf-8'))
        if (r['input_hash']!=request['input_hash'] or r['database_sync_allowed'] or
                r['run_id']!=run_id or r['video_id']!=request['video_id']):
            raise ValueError('Input/scope mismatch')
        r={**r,'original_category':request['original_category']}
        if r['execution_status']=='completed':
            checked=accept(request,r['raw_response'],taxonomy,set())
            if (checked['effective_category_id']!=r['effective_category_id'] or
                    checked['effective_category']!=r['effective_category']):
                raise ValueError('Saved category differs from validated response')
            reason=decisions.get(request['video_id'])
            if filler_only(request['sources']) and r['effective_category']!='unknown':
                reason=reason or 'Only generic utterances; category unsupported'
            if reason and r['effective_category']!='unknown':
                # Retain the proposal in full, and abstain rather than substitute
                # another category without a new supported model result.
                r={**r,'qwen_proposed_category':r['effective_category'],
                   'qwen_proposed_category_id':r['effective_category_id'],
                   'qwen_proposed_evidence':r['evidence'],'evidence':[],
                   'effective_category':'unknown','effective_category_id':taxonomy['category_ids']['unknown'],
                   'classification_source':'insufficient_evidence_after_review',
                   'status':'unknown','review':{'method':'agent_content_evidence_review','reason':reason}}
        records.append(r)
        atomic_json(out/(request['video_id']+'.json'),r)
    valid=[r for r in records if r['execution_status']=='completed']
    report={'total_processed':len(records),'successfully_classified':sum(r['effective_category']!='unknown' for r in valid),
            'unknown_abstained':sum(r['effective_category']=='unknown' for r in valid),
            'failed':sum(r['execution_status']=='failed' for r in records),
            'invalid_classifications':sum(r['execution_status']=='invalid' for r in records),
            'unsupported_category_proposals_rejected':sum('qwen_proposed_category' in r or bool(r.get('rejected_category_proposal')) for r in records),
            'category_distribution':dict(Counter(r['effective_category'] for r in valid)),
            'database_writes':0,'outside_approved_172_processed':0,'other_133_processed':0,
            'model':valid[0]['model'] if valid else None,'revision':valid[0]['revision'] if valid else None,
            'raw_results':str(run/'results.jsonl'),'reviewed_results':str(out/'results.jsonl'),
            'confidence':'Not requested or calibrated; null in records',
            'review_limit':'Conservative agent review, not independent human ground truth'}
    atomic_json(out/'report.json',report)
    atomic_json(out/'review_decisions.json',decisions)
    (out/'results.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in records),encoding='utf-8')
    return report
