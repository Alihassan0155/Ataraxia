"""Atomic file records; validated per-video files are authoritative, not JSONL."""
import hashlib
import json
import os
from pathlib import Path
import uuid

from ataraxia.distributed.common import lock, safe_id, sha, under


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def atomic_bytes(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with tmp.open('wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def write(path, value):
    atomic_bytes(path, (json.dumps(value, ensure_ascii=False, indent=2,
                                  allow_nan=False)+'\n').encode('utf-8'))


def save_array(path, vector):
    import io
    import numpy as np
    buf = io.BytesIO()
    np.save(buf, vector, allow_pickle=False)
    atomic_bytes(path, buf.getvalue())


def validate_array(path, dimensions, tolerance):
    import numpy as np
    vector = np.load(path, allow_pickle=False)
    if vector.shape != (dimensions,) or vector.dtype != np.dtype('float32'):
        raise ValueError('Embedding shape/dtype mismatch')
    if not np.isfinite(vector).all() or abs(float(np.linalg.norm(vector))-1) > tolerance:
        raise ValueError('Embedding must be finite and unit-normalized')
    return vector


def complete_record(run, path, frozen):
    from jsonschema import Draft202012Validator, FormatChecker
    record = read(path)
    Draft202012Validator(read(run/'definitions/record_schema'), format_checker=FormatChecker()).validate(record)
    Draft202012Validator(read(run/'definitions/schema')).validate(record['semantic'])
    if record['status'] != 'complete' or record['run_fingerprint'] != frozen['fingerprint']:
        raise ValueError('Completion/frozen configuration mismatch')
    vid = safe_id(record['video_id'])
    if path.parent.parent.name != vid:
        raise ValueError('Video path/ID mismatch')
    if path.parent.name != record['source_fingerprint']:
        raise ValueError('Source version path mismatch')
    if digest(record['source_hashes']) != record['source_fingerprint']:
        raise ValueError('Source hashes do not match their fingerprint')
    if (record['schema_version'] != frozen['config']['schema_version'] or
            record['extractor'] != frozen['config']['extractor'] or
            record['extraction_prompt_version'] != frozen['config']['extraction_prompt_version'] or
            record['definitions'] != frozen['definition_hashes']):
        raise ValueError('Schema/extractor/definitions mismatch')
    semantic_path = under(run, record['semantic_metadata_path'])
    semantic = read(semantic_path)
    if sha(semantic_path) != record['semantic_metadata_sha256']:
        raise ValueError('Derived metadata hash mismatch')
    if semantic['source_fingerprint'] != record['source_fingerprint']:
        raise ValueError('Source fingerprint mismatch')
    for key in ('semantic', 'semantic_description', 'video_id', 'run_fingerprint', 'embedding_input_sha256'):
        if semantic[key] != record[key]:
            raise ValueError(f'Completed record differs from metadata stage: {key}')
    if record['schema_version'] == 'semantic-record-v2':
        if semantic.get('source_provenance') != record.get('source_provenance'):
            raise ValueError('Completed record differs from deterministic provenance stage')
    inp = under(run, record['embedding_input_path'])
    if sha(inp) != record['embedding_input_sha256']:
        raise ValueError('Embedding input hash mismatch')
    emb = record['embedding']
    cfg = frozen['config']['embedder']
    if any(emb.get(k) != v for k, v in cfg.items()):
        raise ValueError('Embedding settings mismatch')
    if emb['checkpoint'] != cfg['checkpoint'] or emb['revision'] != cfg['revision']:
        raise ValueError('Embedding model mismatch')
    if emb['dimensions'] != cfg['expected_dimensions']:
        raise ValueError('Embedding dimensions mismatch')
    ep = under(run, emb['path'])
    if sha(ep) != emb['sha256']:
        raise ValueError('Embedding file hash mismatch')
    validate_array(ep, emb['dimensions'], cfg['normalization_tolerance'])
    taxonomy, template = read(run/'definitions/taxonomy'), read(run/'definitions/template')
    if record['taxonomy_version'] != taxonomy['version'] or record['template_version'] != template['version']:
        raise ValueError('Taxonomy/template version mismatch')
    data = record['semantic']
    if (data['primary_category'] not in taxonomy['categories'] or
            any(c not in taxonomy['categories'] for c in data['secondary_categories']) or
            data['video_format'] not in taxonomy['formats'] or data['content_style'] not in taxonomy['styles']):
        raise ValueError('Completed record taxonomy mismatch')
    if data['subcategory'] is not None and data['subcategory'] not in taxonomy['categories'][data['primary_category']]:
        raise ValueError('Completed record subcategory mismatch')
    return record


def rebuild_manifest(run, frozen):
    records, errors = [], []
    for path in sorted((run/'videos').glob('*/*/record.json')):
        try:
            record = complete_record(run, path, frozen)
            records.append({'video_id':record['video_id'], 'source_fingerprint':record['source_fingerprint'],
                            'record':path.relative_to(run).as_posix(), 'record_sha256':sha(path),
                            'completed_at':record['completed_at']})
        except Exception as exc:
            errors.append({'path':path.relative_to(run).as_posix(), 'error':str(exc)})
    lines = ''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in records)
    atomic_bytes(run/'manifests/processing_manifest.jsonl', lines.encode('utf-8'))
    write(run/'reports/integrity.json', {'verified_versions':len(records), 'errors':errors})
    return records, errors
