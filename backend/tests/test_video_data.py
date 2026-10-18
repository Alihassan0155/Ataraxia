import copy
import csv
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from backend.video_data.artifacts import Reader, fingerprint, validate_vector, canonical, entity, context_entity, under, embedding_entity
from backend.video_data.__main__ import synchronize
from backend.video_data.config import DatabaseSettings, TABLES
from backend.video_data.repository import REQUIRED, compatibility, Repository

PROJECT = Path(__file__).resolve().parents[2]
ANNOTATION = PROJECT/'annotation'
sys.path.insert(0,str(ANNOTATION/'src'))


class FakeRepository:
    """In-memory transactional target; not a substitute for PostgreSQL testing."""
    def __init__(self):
        self.rows = {}

    def put_bundle(self, rows):
        staged = copy.deepcopy(self.rows)
        counts = {'inserted':0,'updated':0,'skipped':0}
        for row in rows:
            key = (row['table'],row['key'])
            prior = staged.get(key)
            if prior and prior['content_hash']==row['content_hash']:
                counts['skipped'] += 1
            elif prior and row['table']!='videos':
                raise ValueError('Immutable conflict')
            else:
                counts['updated' if prior else 'inserted'] += 1
                staged[key] = row
        self.rows = staged
        return counts


def fixture(root, name='fixture_run', run_fingerprint='a'*64):
    from ataraxia.semantic.sources import bundle
    from ataraxia.semantic.provenance import build_provenance
    from ataraxia.semantic.representation import render
    from ataraxia.semantic.storage import sha
    def write(path,value):
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    cfg = json.loads((ANNOTATION/'semantic_pipeline/configs/pipeline_v12.json').read_text())
    row = {'assigned_id':'FVTEST1','video_id':'FVTEST1','title':'Training demo',
           'file_path':'data/videos/FVTEST1.mp4','language':'en','duration_seconds':'10',
           'context_path':'data/normalized/preprocessed_merged_v2/context/FVTEST1.json',
           'transcript_path':'data/normalized/preprocessed_merged_v2/transcripts/FVTEST1.txt'}
    metadata = root/cfg['metadata_csv']
    metadata.parent.mkdir(parents=True,exist_ok=True)
    with metadata.open('w',newline='',encoding='utf-8') as stream:
        writer = csv.DictWriter(stream,fieldnames=list(row))
        writer.writeheader(); writer.writerow(row)
    context = {'video_id':'FVTEST1','transcript':'A speaker explains a training exercise.',
               'metadata_caption':'Training','acoustic_features':{}}
    write(root/row['context_path'],context)
    tr = root/row['transcript_path'];tr.parent.mkdir(parents=True,exist_ok=True)
    tr.write_text(context['transcript'],encoding='utf-8')
    annotation = {'video_id':'FVTEST1','valence':0.1,'arousal':0.3,'recovery_suitability':0.4,
                  'emotions':dict(joy=1,sadness=0,anger=0,fear_anxiety=0,surprise=0,disgust=0,calm_contentment=0,neutral=0),
                  'dominant_emotion':'joy','confidence':0.5,'model':'gemini-3.8-flash',
                  'available_modalities':dict(visual=True,audio=True,speech_text=True,motion_temporal=True),
                  'evidence':dict(visual='A speaker explains a training exercise.',audio=None,speech_text=context['transcript'],motion_temporal=None),
                  'ambiguity_notes':'none','run_metadata':{'prompt_version':'v1.0'}}
    prediction = root/cfg['gemini_sources'][0];prediction.parent.mkdir(parents=True,exist_ok=True)
    prediction.write_text(json.dumps(annotation)+'\n',encoding='utf-8')
    ref = {'path':cfg['gemini_sources'][0],'line':1}
    job = bundle(root,cfg,'FVTEST1',{'annotation':annotation,'annotation_sha256':fingerprint(annotation),'annotation_ref':ref},row)
    run = root/'semantic_pipeline/runs'/name
    defs = run/'definitions';defs.mkdir(parents=True)
    schema = json.loads((ANNOTATION/cfg['schema']).read_text())
    taxonomy = json.loads((ANNOTATION/cfg['taxonomy']).read_text())
    template = json.loads((ANNOTATION/cfg['template']).read_text())
    for key,value in [('schema',schema),('taxonomy',taxonomy),('template',template),
                       ('record_schema',json.loads((ANNOTATION/cfg['record_schema']).read_text()))]:
        write(defs/key,value)
    (defs/'metadata_csv').write_bytes(metadata.read_bytes())
    frozen = {'fingerprint':run_fingerprint,'config':cfg,'definition_hashes':{}}
    write(run/'frozen.json',frozen)
    semantic = {}
    for field,rule in schema['properties'].items():
        resolved = schema['$defs'][rule['$ref'].split('/')[-1]] if '$ref' in rule else rule
        semantic[field] = [] if resolved.get('type')=='array' else None
    semantic.update(primary_category='unknown',video_format='unknown',content_style='unknown',
                    semantic_summary=context['transcript'],extraction_confidence=0.5,category_ambiguity=True)
    semantic, provenance = build_provenance(semantic,schema,taxonomy,job['sources'])
    description,text = render(semantic,job,template)
    directory = run/'videos/FVTEST1'/job['source_fingerprint'];directory.mkdir(parents=True)
    inp = directory/'embedding_input.txt';inp.write_text(text,encoding='utf-8',newline='')
    vector = np.zeros(1024,dtype=np.float32);vector[0]=1
    np.save(directory/'embedding.npy',vector)
    artifact = {'schema_version':'semantic-record-v2','video_id':'FVTEST1',
                'source_fingerprint':job['source_fingerprint'],'run_fingerprint':run_fingerprint,
                'semantic':semantic,'semantic_description':description,'source_provenance':provenance,
                'embedding_input_sha256':sha(inp),'extracted_at':'2026-10-17T00:00:00Z'}
    write(directory/'semantic_metadata.json',artifact)
    record = {**artifact,'status':'complete','completed_at':'2026-10-17T00:01:00Z',
              'source_references':job['references'],'source_hashes':job['hashes'],
              'extractor':cfg['extractor'],'extraction_prompt_version':cfg['extraction_prompt_version'],
              'definitions':{},'taxonomy_version':taxonomy['version'],'template_version':template['version'],
              'quality':{},'language_provenance':{},'transcript_budget':{},'gemini_prompt_provenance':{},
              'semantic_metadata_path':(directory/'semantic_metadata.json').relative_to(run).as_posix(),
              'semantic_metadata_sha256':sha(directory/'semantic_metadata.json'),
              'embedding_input_path':inp.relative_to(run).as_posix(),
              'embedding':{**cfg['embedder'],'dimensions':1024,'path':(directory/'embedding.npy').relative_to(run).as_posix(),
                           'sha256':sha(directory/'embedding.npy')}}
    write(directory/'record.json',record)
    write(directory/'state.json',{'status':'complete','attempts':1})
    write(root/'semantic_pipeline/configs/taxonomy.json',taxonomy)
    return run,prediction,metadata,directory


class VideoDataTests(unittest.TestCase):
    def test_embedding_identity_duplicate_import_is_idempotent(self):
        record={'embedding':{'checkpoint':'model','revision':'rev1'},
                'template_version':'v1','embedding_input_sha256':'a'*64}
        vector=np.zeros(1024,dtype=np.float32);vector[0]=1
        first=embedding_entity('FVTEST1','semantic','run',record,vector)
        duplicate=embedding_entity('FVTEST1','semantic','run',copy.deepcopy(record),vector.copy())
        self.assertEqual(first,duplicate)
        self.assertNotEqual(first['key'],'semantic')
        self.assertEqual(first['columns']['semantic_id'],'semantic')
        repo=FakeRepository()
        self.assertEqual(repo.put_bundle([first])['inserted'],1)
        self.assertEqual(repo.put_bundle([duplicate])['skipped'],1)
        self.assertEqual(len(repo.rows),1)

    def test_embedding_versions_share_semantic_fk_but_have_distinct_ids(self):
        record={'embedding':{'checkpoint':'model','revision':'rev1'},
                'template_version':'v1','embedding_input_sha256':'a'*64}
        vector=np.zeros(1024,dtype=np.float32);vector[0]=1
        versions=[embedding_entity('FVTEST1','semantic','run',record,vector)]
        for field in ('checkpoint','revision','template_version','embedding_input_sha256','run_id'):
            changed=copy.deepcopy(record)
            run='run2' if field=='run_id' else 'run'
            if field in ('checkpoint','revision'):changed['embedding'][field]+='-new'
            elif field!='run_id':changed[field]='new'
            versions.append(embedding_entity('FVTEST1','semantic',run,changed,vector))
        self.assertEqual(len({v['key'] for v in versions}),len(versions))
        self.assertEqual({v['columns']['semantic_id'] for v in versions},{'semantic'})
        repo=FakeRepository()
        self.assertEqual(repo.put_bundle(versions)['inserted'],len(versions))
        self.assertEqual(repo.put_bundle(versions)['skipped'],len(versions))
        self.assertNotEqual(versions[0]['key'],embedding_entity('FVTEST1','other','run',record,vector)['key'])

    def test_nonfinite_acoustics_become_explicit_missing_values_only_in_import(self):
        original={'pitch':float('nan'),'loudness':1.2}
        row=context_entity('FVTEST1',{}, {},'Transcript',original)
        self.assertIsNone(row['payload']['acoustic_features']['pitch'])
        self.assertEqual(row['payload']['acoustic_features']['loudness'],1.2)
        self.assertTrue(row['payload']['nonfinite_values_stored_as_null'])
        self.assertTrue(np.isnan(original['pitch']))

    def test_existing_data_junction_target_allowed_arbitrary_paths_rejected(self):
        data=(ANNOTATION/'data').resolve()
        self.assertEqual(under(ANNOTATION,data/'example.json'),data/'example.json')
        with self.assertRaises(ValueError):under(ANNOTATION,PROJECT/'outside-data/example.json')
        with self.assertRaises(ValueError):under(ANNOTATION,'data/../outside.json')

    def test_configuration_never_repr_credentials(self):
        settings = DatabaseSettings.load('/nonexistent',{'DATABASE_URL':'postgres://name:secret@host/db'})
        self.assertNotIn('secret',repr(settings))
        with self.assertRaises(ValueError):
            DatabaseSettings.load('/nonexistent',{})
        with self.assertRaisesRegex(ValueError,'placeholder'):
            DatabaseSettings.load('/nonexistent',{'DATABASE_URL':'postgresql://user:[YOUR-PASSWORD]@host/db'})

    def test_vectors_reject_invalid_inputs_without_normalizing(self):
        good = np.zeros(1024,dtype=np.float32);good[0]=1
        validate_vector(good)
        for bad in [good.astype(np.float64),good[:10],good*2,np.full(1024,np.nan,dtype=np.float32)]:
            with self.assertRaises(ValueError):validate_vector(bad)

    def test_historical_import_duplicate_and_incremental_versions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);run,prediction,metadata,_=fixture(root)
            target=FakeRepository()
            first=synchronize(root,[run],[prediction],metadata,target)
            self.assertEqual(first['failed'],0,first['issues'])
            self.assertEqual(first['valid_semantic_records'],1)
            self.assertEqual(first['models_executed'],0)
            embedding=next(v for (t,_),v in target.rows.items() if t=='video_embeddings')
            self.assertNotEqual(embedding['key'],embedding['columns']['semantic_id'])
            self.assertIn(('video_semantics',embedding['columns']['semantic_id']),target.rows)
            count=len(target.rows)
            second=synchronize(root,[run],[prediction],metadata,target)
            self.assertEqual(len(target.rows),count)
            self.assertEqual(second['database_changes']['inserted'],0)
            self.assertGreater(second['skipped'],0)
            other,_,_,_=fixture(root,'second_run','b'*64)
            third=synchronize(root,[run,other],[prediction],metadata,target)
            self.assertEqual(third['failed'],0,third['issues'])
            self.assertEqual(sum(t=='video_semantics' for t,_ in target.rows),2)
            self.assertEqual(sum(t=='video_embeddings' for t,_ in target.rows),2)
            self.assertEqual(sum(t=='affect_annotations' for t,_ in target.rows),1)

    def test_corrupt_embedding_and_incomplete_tail_not_imported_as_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);run,prediction,metadata,directory=fixture(root)
            (directory/'embedding.npy').write_bytes(b'broken')
            with prediction.open('a') as stream:stream.write('{"video_id":')
            target=FakeRepository()
            report=synchronize(root,[run],[prediction],metadata,target)
            self.assertGreater(report['failed'],0)
            self.assertGreater(report['incomplete'],0)
            self.assertEqual(sum(t=='video_embeddings' for t,_ in target.rows),0)

    def test_dry_run_does_not_connect(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);run,prediction,metadata,_=fixture(root)
            with patch('backend.video_data.config.connect',side_effect=AssertionError('No network')):
                report=synchronize(root,[run],[prediction],metadata)
            self.assertEqual(report['failed'],0,report['issues'])
            self.assertEqual(report['mode'],'dry-run')

    def test_immutable_conflict_rolls_back_bundle_and_can_resume(self):
        repo=FakeRepository()
        original=entity('processing_runs','id',{'version':1},kind='semantic',name='test')
        repo.put_bundle([original])
        count=len(repo.rows)
        with self.assertRaises(ValueError):
            repo.put_bundle([entity('processing_runs','another',{'version':1}),
                             entity('processing_runs','id',{'version':2})])
        self.assertEqual(len(repo.rows),count)
        self.assertEqual(repo.put_bundle([original])['skipped'],1)

    def test_mapping_compatibility_and_vector_dimensions(self):
        inventory={'columns':[],'types':[{'schema':'public','table':'video_embeddings','column':'embedding','format':'vector(1024)'}], 'constraints':[], 'extensions':[{'name':'vector','schema':'extensions'}]}
        for table,columns in REQUIRED.items():
            inventory['columns'] += [{'schema':'public','table':table,'column':name} for name in columns]
            key='video_id' if table=='videos' else 'id'
            inventory['constraints'].append({'schema':'public','table':table,'kind':'p','definition':f'PRIMARY KEY ({key})'})
        self.assertTrue(compatibility(inventory,'public',{name:name for name in TABLES})['compatible'])
        inventory['types'][0]['format']='vector(768)'
        self.assertFalse(compatibility(inventory,'public',{name:name for name in TABLES})['compatible'])


if __name__=='__main__':unittest.main()
