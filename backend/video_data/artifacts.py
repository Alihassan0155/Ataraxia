"""Read frozen outputs through existing validators. No torch/transformers imports."""
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import sys


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def fingerprint(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def entity(table, key, payload, **columns):
    return {'table':table, 'key':key, 'payload':payload,
            'content_hash':fingerprint(payload), 'columns':columns}


def safe_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', value):
        raise ValueError('Invalid/missing video_id')
    return value


def under(root, value):
    path = Path(value)
    path = path if path.is_absolute() else root/path
    # Lexical root-relative references may use the existing data junction.
    if '..' in path.parts:
        raise ValueError('Parent traversal in artifact reference')
    try:
        path.absolute().relative_to(root.absolute())
    except ValueError:
        # Current metadata preserves pre-refactor absolute paths under the existing
        # data junction. Accept that target, not arbitrary external directories.
        try:
            path.resolve().relative_to((root/'data').resolve())
        except ValueError:
            raise ValueError('Artifact reference outside annotation workspace/data target')
    return path


def adapters(root):
    src = str(root/'src')
    if src not in sys.path:
        sys.path.insert(0, src)
    from ataraxia.semantic.storage import complete_record, read, sha
    from ataraxia.semantic.sources import metadata, bundle
    from ataraxia.semantic.representation import validate, render
    from ataraxia.annotation.common import VideoAnnotation
    return complete_record, read, sha, metadata, bundle, validate, render, VideoAnnotation


def metadata_rows(path):
    result = {}
    with path.open(encoding='utf-8-sig', newline='') as stream:
        for row in csv.DictReader(stream):
            vid = safe_id(row.get('assigned_id') or row.get('video_id'))
            if vid in result:
                raise ValueError('Duplicate metadata video_id')
            result[vid] = row
    return result


def video(vid, row):
    # Full row is retained, including optional source-specific columns.
    duration = row.get('duration_seconds')
    duration = float(duration) if duration not in (None,'') else None
    if duration is not None and (not __import__('math').isfinite(duration) or duration < 0):
        raise ValueError('Invalid video duration')
    return entity('videos', safe_id(vid), row, title=row.get('title'), language=row.get('language'),
                  source_dataset=row.get('source_dataset'), source_id=row.get('source_id'),
                  duration_seconds=duration, orientation=row.get('orientation'),
                  media_uri=row.get('file_path'), media_sha256=row.get('media_sha256') or None,
                  availability='local_reference_only')


def context_entity(vid, row, context, transcript, features=None):
    payload = {'metadata':row, 'context':context, 'transcript':transcript,
               'acoustic_features':features if features is not None else context.get('acoustic_features', {})}
    replaced = []
    def finite(value, path=''):
        if isinstance(value,float) and not math.isfinite(value):
            replaced.append(path)
            return None  # PostgreSQL JSON has no NaN/Infinity; retain explicit missingness.
        if isinstance(value,dict):
            return {k:finite(v,path+'/'+k) for k,v in value.items()}
        if isinstance(value,list):
            return [finite(v,path+'/'+str(i)) for i,v in enumerate(value)]
        return value
    payload = finite(payload)
    if replaced:
        payload['nonfinite_values_stored_as_null'] = replaced
    return entity('video_context', fingerprint([vid,payload]), payload, video_id=vid,
                  transcript=transcript, acoustic_features=payload['acoustic_features'])


def affect(vid, item, run_id):
    return entity('affect_annotations', fingerprint([run_id,item]), item, video_id=vid, run_id=run_id,
                  model=item['model'], valence=item['valence'], arousal=item['arousal'],
                  recovery_suitability=item['recovery_suitability'], emotions=item['emotions'],
                  dominant_emotion=item['dominant_emotion'], confidence=item['confidence'])


def embedding_entity(vid, semantic_id, run_id, record, vector):
    columns = dict(video_id=vid, run_id=run_id, semantic_id=semantic_id,
                   model=record['embedding']['checkpoint'], revision=record['embedding']['revision'],
                   template_version=record['template_version'], input_hash=record['embedding_input_sha256'])
    # Versioned namespace prevents accidental reuse of the old semantic-only key.
    embedding_id = fingerprint({'identity_version':'video-embedding-v1', **columns})
    return entity('video_embeddings',embedding_id,record['embedding'],
                  **columns, embedding=vector.tolist())


class Reader:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.api = adapters(self.root)
        self._jsonl = {}
        self._affect_runs = {}

    def affect_run(self, prediction):
        prediction = prediction.absolute()
        if prediction not in self._affect_runs:
            origin = prediction.relative_to(self.root).as_posix()
            payload = {'kind':'affect', 'prediction_path':origin}
            # Reuse known run configuration identity without importing env/secrets.
            for parent in prediction.parents:
                config = parent/'configuration.json'
                if config.is_file():
                    payload['configuration_path'] = config.relative_to(self.root).as_posix()
                    payload['configuration_sha256'] = hashlib.sha256(config.read_bytes()).hexdigest()
                    break
                if parent == self.root:
                    break
            rid = fingerprint(payload)
            self._affect_runs[prediction] = entity('processing_runs',rid,payload,kind='affect',name=origin)
        return self._affect_runs[prediction]

    def referenced_annotation(self, reference, expected_hash):
        path = under(self.root, reference['path'])
        if path not in self._jsonl:
            # Fixed byte snapshot, including concurrent-append protection.
            data = path.read_bytes()
            self._jsonl[path] = data.splitlines() if data.endswith(b'\n') else data.splitlines()[:-1]
        index = reference['line']-1
        if index < 0:
            raise ValueError('Invalid annotation line number')
        item = json.loads(self._jsonl[path][index].decode('utf-8-sig'))
        if fingerprint(item) != expected_hash:
            raise ValueError('Referenced Gemini annotation hash mismatch')
        self.api[-1].model_validate(item)
        return item

    def semantic_bundle(self, run, path, frozen, rows):
        complete, read, sha, _, bundle, validate, render, _ = self.api
        record = complete(run, path, frozen)
        vid = safe_id(record['video_id'])
        if vid not in rows:
            raise ValueError('Semantic ID absent from frozen metadata')
        row = rows[vid]
        item = self.referenced_annotation(record['source_references']['gemini'], record['source_hashes']['gemini'])
        if item['video_id'] != vid:
            raise ValueError('Semantic/Gemini video_id mismatch')
        job = bundle(self.root, frozen['config'], vid,
                     {'annotation':item, 'annotation_sha256':fingerprint(item),
                      'annotation_ref':record['source_references']['gemini']}, row)
        if job['source_fingerprint'] != record['source_fingerprint']:
            raise ValueError('Current source files do not match semantic source hashes')
        validate(record['semantic'], read(run/'definitions/schema'), read(run/'definitions/taxonomy'), job['sources'])
        description, text = render(record['semantic'], job, read(run/'definitions/template'))
        if description != record['semantic_description'] or text.encode('utf-8') != (run/record['embedding_input_path']).read_bytes():
            raise ValueError('Semantic embedding input does not match frozen template')
        if record['schema_version'] == 'semantic-record-v2':
            from ataraxia.semantic.provenance import validate_provenance
            validate_provenance(record['semantic'], record['source_provenance'], read(run/'definitions/schema'),
                                read(run/'definitions/taxonomy'), job['sources'])
        run_id = fingerprint(['semantic', run.relative_to(self.root).as_posix(), frozen['fingerprint']])
        run_payload = {'name':run.name, 'path':run.relative_to(self.root).as_posix(), 'frozen':frozen}
        ctxpath = record['source_references'].get('context')
        context = read(under(self.root, ctxpath)) if ctxpath else {}
        trpath = record['source_references'].get('transcript')
        transcript = under(self.root,trpath).read_text(encoding='utf-8-sig') if trpath else context.get('transcript','')
        feature_path = self.root/frozen['config']['context_dir']
        feature_path = feature_path.parent/'acoustic_features'/f'{vid}.json'
        features = read(feature_path) if feature_path.exists() else None
        ctx = context_entity(vid,row,context,transcript,features)
        affect_run = self.affect_run(under(self.root,record['source_references']['gemini']['path']))
        ann = affect(vid,item,affect_run['key'])
        sid = fingerprint([run_id,vid,record['source_fingerprint'],sha(path)])
        sem = record['semantic']
        import numpy as np
        vector = np.load(run/record['embedding']['path'], allow_pickle=False)
        validate_vector(vector)
        return [video(vid,row), entity('processing_runs',run_id,run_payload, kind='semantic', name=run.name),
                affect_run, ctx, ann,
                entity('video_semantics',sid,record, video_id=vid, run_id=run_id,
                       context_id=ctx['key'], affect_id=ann['key'], primary_category=sem['primary_category'],
                       semantic_summary=sem['semantic_summary'], topics=sem['topics'], tags=sem['tags']),
                embedding_entity(vid,sid,run_id,record,vector)]


def validate_vector(vector):
    import numpy as np
    if vector.shape != (1024,) or vector.dtype != np.dtype('float32'):
        raise ValueError('Embedding must be float32 with exactly 1024 dimensions')
    if not np.isfinite(vector).all() or abs(float(np.linalg.norm(vector))-1)>0.0001:
        raise ValueError('Embedding must be finite and L2 normalized; importer never normalizes it')


def categories(path):
    taxonomy = json.loads(path.read_text(encoding='utf-8-sig'))
    # Reuse the actual canonical category aliases, not an independent taxonomy.
    from ataraxia.semantic.normalization import ALIASES
    result = []
    for name, subs in taxonomy['categories'].items():
        payload = {'taxonomy_version':taxonomy['version'], 'name':name, 'subcategories':subs,
                   'aliases':sorted(k for k,v in ALIASES.items() if v==name), 'is_onboarding':name!='unknown'}
        result.append(entity('interest_categories',fingerprint([taxonomy['version'],name]),payload,
                             taxonomy_version=taxonomy['version'], name=name, aliases=payload['aliases'],
                             subcategories=subs, is_onboarding=payload['is_onboarding']))
    return result
