"""Read only complete Gemini JSONL records and resolve their existing evidence."""
import csv
import json
from pathlib import Path

from ataraxia.annotation.common import VideoAnnotation
from ataraxia.runtime.config import resolve_path
from .storage import digest, read, sha, safe_id


def reference(root, path):
    path = Path(path)
    # Keep lexical project-relative paths, including the existing data junction.
    try:
        return path.absolute().relative_to(root.absolute()).as_posix()
    except ValueError:
        raise ValueError(f'Semantic sources must be referenceable from project root: {path}')


def annotations(root, config):
    rows, errors, conflicts = {}, [], set()
    for name in config['gemini_sources']:
        path = resolve_path(root, name)
        if not path.exists():
            continue  # Gemini may not have written its first result yet.
        # Fixed read snapshot: do not chase concurrent appends forever.
        size = path.stat().st_size
        with path.open('rb') as f:
            line_number = 0
            while f.tell() < size:
                line_number += 1
                line = f.readline(min(1048577, size-f.tell()))
                if len(line) > 1048576:
                    errors.append({'source':name, 'line':line_number, 'error':'Oversize annotation line'})
                    while not line.endswith(b'\n') and f.tell() < size:
                        line = f.readline(min(1048577, size-f.tell()))
                    continue
                if not line.endswith(b'\n'):
                    break  # Never parse a partially written final record.
                try:
                    item = json.loads(line.decode('utf-8-sig'))
                    VideoAnnotation.model_validate(item)
                    vid = safe_id(item['video_id'])
                    if 'gemini' not in item.get('model', '').lower():
                        raise ValueError('Not a Gemini prediction')
                    h = digest(item)
                    if vid in rows and rows[vid]['annotation_sha256'] != h:
                        conflicts.add(vid)
                        raise ValueError(f'Conflicting duplicate Gemini ID: {vid}')
                    rows[vid] = {'annotation':item, 'annotation_sha256':h,
                                 'annotation_ref':{'path':reference(root, root/name), 'line':line_number}}
                except (ValueError, KeyError, TypeError) as exc:
                    errors.append({'source':name, 'line':line_number, 'error':str(exc)})
    for vid in conflicts:
        rows.pop(vid, None)
    return rows, errors


def metadata(run):
    with (run/'definitions/metadata_csv').open(encoding='utf-8-sig', newline='') as f:
        result = {}
        for row in csv.DictReader(f):
            vid = safe_id(row.get('assigned_id') or row.get('video_id'))
            if vid in result:
                raise ValueError(f'Duplicate metadata ID: {vid}')
            result[vid] = row
        return result


def transcript_excerpt(text, limit):
    if len(text) <= limit:
        return text, {'truncated':False, 'original_characters':len(text)}
    # Explicitly retain beginning/middle/end, not an invisible tokenizer crop.
    width = max(1, (limit-100)//3)
    middle = len(text)//2
    value = text[:width]+'\n[TRANSCRIPT SECTION OMITTED]\n'+text[middle-width//2:middle+width//2]+'\n[TRANSCRIPT SECTION OMITTED]\n'+text[-width:]
    return value, {'truncated':True, 'original_characters':len(text),
                   'retained_characters':len(value), 'policy':'beginning-middle-end characters v1'}


def bundle(root, config, vid, annotation, row):
    context_path = root/config['context_dir']/f'{vid}.json'
    context = read(context_path) if context_path.exists() else {}
    if context and context.get('video_id') != vid:
        raise ValueError('Context video ID mismatch')
    transcript_path = root/config['transcript_dir']/f'{vid}.txt'
    text = transcript_path.read_text(encoding='utf-8-sig') if transcript_path.exists() else context.get('transcript', '')
    excerpt, budget = transcript_excerpt(text, config['extractor']['transcript_max_characters'])
    item = annotation['annotation']
    sources = {k:(item['evidence'].get(k) or '') for k in ('visual', 'audio', 'speech_text', 'motion_temporal')}
    sources.update(transcript=excerpt, caption=context.get('metadata_caption') or row.get('metadata_caption', ''),
                   title=row.get('title', ''), original_category=row.get('category_original', ''),
                   recorded_language=row.get('language', ''),
                   acoustic_features=json.dumps(context.get('acoustic_features', {}), sort_keys=True))
    refs = {'gemini':annotation['annotation_ref'],
            'transcript':reference(root, transcript_path) if transcript_path.exists() else None,
            'context':reference(root, context_path) if context_path.exists() else None,
            'metadata_csv':config['metadata_csv'], 'metadata_video_id':vid}
    hashes = {'gemini':annotation['annotation_sha256'], 'metadata_row':digest(row),
              'context':sha(context_path) if context_path.exists() else None,
              'transcript':sha(transcript_path) if transcript_path.exists() else digest(text)}
    missing = [k for k in ('visual', 'audio', 'speech_text', 'motion_temporal', 'transcript') if not sources[k]]
    return {'video_id':vid, 'sources':sources, 'references':refs, 'hashes':hashes,
            'source_fingerprint':digest(hashes), 'transcript_budget':budget,
            'missing_evidence':missing, 'gemini_prompt':item.get('run_metadata', {}),
            'available_modalities':item['available_modalities'],
            'language_provenance':{'value':row.get('language') or None,
                                  'status':row.get('language_status') or None,
                                  'method':row.get('language_scan_method') or None}}
