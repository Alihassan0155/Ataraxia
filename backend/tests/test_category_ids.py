"""CPU-only category contract and catalogue compatibility tests; no inference."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'annotation/src'))
from ataraxia.semantic.category_ids import (choices,decode_selection,map_legacy,
    supported_secondary,validate_selection,wire_contract)
from ataraxia.semantic.models import Extractor
from ataraxia.semantic.normalization import normalize_semantic
from ataraxia.semantic.storage import complete_record,read,sha
from ataraxia.semantic.worker import Worker
from ataraxia.semantic.sources import bundle
from backend.video_data.catalogue import category_resolution
from backend.tests.test_video_data import fixture

TAX=read(ROOT/'annotation/semantic_pipeline/configs/taxonomy_category_ids_v1.json')
SCHEMA=read(ROOT/'annotation/semantic_pipeline/schemas/semantic_metadata.v2.schema.json')


class CategoryIdTests(unittest.TestCase):
    def test_exactly_19_existing_ids_in_wire_schema(self):
        allowed,wire=wire_contract(TAX,SCHEMA)
        self.assertEqual(len(allowed),19)
        self.assertEqual(set(wire['properties']['primary_category']['enum']),set(TAX['category_ids'].values()))
        self.assertEqual(wire['properties']['secondary_categories']['maxItems'],0)
        self.assertEqual(SCHEMA['properties']['primary_category']['type'],'string')

    def test_every_valid_id_decodes_and_preserves_other_fields(self):
        for name,identifier in TAX['category_ids'].items():
            value={'primary_category':identifier,'secondary_categories':[],
                   'topics':['Original topic'],'tags':['Original tag'],'activities':['Running'],
                   'subjects':['A person'],'semantic_summary':'An original semantic summary.'}
            before=copy.deepcopy(value)
            decoded,selection=decode_selection(value,TAX)
            self.assertEqual(decoded,{**value,'primary_category':name})
            self.assertEqual(value,before)
            validate_selection({'semantic':decoded,'category_selection':selection},TAX)

    def test_invalid_names_aliases_ids_lists_and_multiple_categories_rejected(self):
        for value in ['Comedy','humour','unknown','sports and fitnes','made-up-id',
                      [TAX['category_ids']['Comedy']],None,1,' '+TAX['category_ids']['Comedy']]:
            with self.subTest(value=value),self.assertRaises(ValueError):
                decode_selection({'primary_category':value,'secondary_categories':[]},TAX)
        with self.assertRaises(ValueError):
            decode_selection({'primary_category':TAX['category_ids']['Comedy'],'secondary_categories':['Gaming']},TAX)

    def test_unknown_id_is_explicit_valid_selection(self):
        value,selection=decode_selection({'primary_category':TAX['category_ids']['unknown'],'secondary_categories':[]},TAX)
        self.assertEqual(value['primary_category'],'unknown')
        self.assertEqual(selection['name'],'unknown')

    def test_id_name_drift_and_missing_categories_fail(self):
        bad=copy.deepcopy(TAX);bad['category_ids']['Comedy']='invented'
        with self.assertRaises(ValueError):choices(bad)
        del bad['category_ids']['Comedy']
        with self.assertRaises(ValueError):choices(bad)

    def test_prompt_lists_ids_and_uses_id_enum_without_loading_model(self):
        class Tokenizer:
            def apply_chat_template(self,messages,**kwargs):return json.dumps(messages)
            def encode(self,text):return [1]
        extractor=Extractor.__new__(Extractor)
        extractor.config={'category_policy':'canonical-id-v1','max_input_tokens':8192}
        extractor.tokenizer=Tokenizer()
        job={'video_id':'V','sources':{},'transcript_budget':{}}
        with patch('ataraxia.semantic.models.gpu',side_effect=AssertionError('No GPU')):
            text=extractor.text(job,'Prompt',TAX,SCHEMA)
        messages=json.loads(text);payload=json.loads(messages[1]['content'])
        listed=json.loads(messages[0]['content'].split('allowed_category_choices:\n',1)[1])
        self.assertEqual(len(listed),19)
        self.assertEqual(listed,choices(TAX))
        self.assertIn('exactly ONE ID',messages[0]['content'])
        self.assertEqual(payload['output_schema']['properties']['primary_category']['enum'],
                         [r['id'] for r in choices(TAX)])

    def test_legacy_mapping_is_unambiguous_and_never_fuzzy(self):
        for label in ['Comedy','Stand-up','humour']:
            self.assertEqual(map_legacy(label,TAX)['name'],'Comedy')
        self.assertEqual(map_legacy('Other',TAX)['status'],'ambiguous_review')
        self.assertEqual(map_legacy('Tutorials',TAX)['status'],'ambiguous_review')
        self.assertEqual(map_legacy('sports and fitnes',TAX)['status'],'unmapped_review')

    def test_original_preserved_dedup_and_human_supported_secondary(self):
        metadata={'category_original':'Stand-up','category':'Comedy'}
        semantic={'id':'S','payload':{'semantic':{'primary_category':'Education'}}}
        review={'method':'human_evidence_review','reviewer':'reviewer-1','semantic_id':'S',
                'category':'Education','supports_category':True,'source':'visual',
                'quote':'A teacher demonstrates a science experiment.'}
        sources={'visual':review['quote']}
        result=category_resolution(metadata,semantic,{'Stand-up':'Comedy'},TAX,review,sources)
        self.assertEqual(result['original_label'],'Stand-up')
        self.assertEqual(result['effective_categories'],['Comedy','Education'])
        self.assertEqual(metadata,{'category_original':'Stand-up','category':'Comedy'})
        for change in [{'semantic_id':'wrong'},{'source':'metadata_caption'},
                       {'method':'model_claim'},{'quote':'fabricated quote'}, {'supports_category':False}]:
            bad={**review,**change}
            result=category_resolution(metadata,semantic,{'Stand-up':'Comedy'},TAX,bad,sources)
            self.assertEqual(result['effective_categories'],['Comedy'])
        semantic['payload']['semantic']['primary_category']='Comedy'
        result=category_resolution(metadata,semantic,{'Stand-up':'Comedy'},TAX,review,sources)
        self.assertEqual(result['effective_categories'],['Comedy'])

    def test_worker_cached_output_uses_strict_contract_without_model(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);run,prediction,manifest,directory=fixture(root)
            worker=Worker(root,root/'config.json',run)
            worker.frozen=read(run/'frozen.json');worker.cfg=copy.deepcopy(worker.frozen['config'])
            worker.cfg['extractor']['category_policy']='canonical-id-v1'
            worker.schema=SCHEMA;worker.taxonomy=TAX;worker.template=read(run/'definitions/template')
            worker.event=lambda *args,**kwargs:None
            record=read(directory/'record.json');annotation=json.loads(prediction.read_text().strip())
            import csv
            with manifest.open(newline='',encoding='utf-8') as f:row=next(csv.DictReader(f))
            job=bundle(root,worker.cfg,'FVTEST1',{'annotation':annotation,
                       'annotation_sha256':record['source_hashes']['gemini'],
                       'annotation_ref':record['source_references']['gemini']},row)
            draft=copy.deepcopy(record['semantic']);draft['primary_category']=TAX['category_ids']['unknown']
            with patch('ataraxia.semantic.models.Extractor.__init__',side_effect=AssertionError('No Qwen')):
                worker.extract([job],cached_outputs={'FVTEST1':json.dumps(draft)})
            artifact=read(directory/'semantic_metadata.json')
            self.assertEqual(artifact['category_selection']['id'],TAX['category_ids']['unknown'])
            self.assertEqual(artifact['semantic']['semantic_summary'],record['semantic']['semantic_summary'])
            self.assertEqual(artifact['semantic']['topics'],record['semantic']['topics'])
            # An invalid label must fail before normalization maps it to Comedy.
            draft['primary_category']='humour'
            worker.extract([job],cached_outputs={'FVTEST1':json.dumps(draft)})
            self.assertEqual(read(directory/'state.json')['status'],'failed')

    def test_strict_completed_record_remains_compatible_with_existing_reader(self):
        from backend.video_data.artifacts import Reader
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);run,_,_,directory=fixture(root)
            frozen=read(run/'frozen.json');frozen['config']['extractor']['category_policy']='canonical-id-v1'
            selection={'policy':'canonical-id-v1','id':TAX['category_ids']['unknown'],
                       'name':'unknown','taxonomy_version':TAX['version']}
            def write(path,value):path.write_text(json.dumps(value),encoding='utf-8')
            write(run/'frozen.json',frozen);write(run/'definitions/taxonomy',TAX)
            artifact=read(directory/'semantic_metadata.json');artifact['category_selection']=selection
            write(directory/'semantic_metadata.json',artifact)
            record=read(directory/'record.json');record['category_selection']=selection
            record['extractor']=frozen['config']['extractor']
            record['semantic_metadata_sha256']=sha(directory/'semantic_metadata.json')
            write(directory/'record.json',record)
            reader=Reader(root)
            items=reader.semantic_bundle(run,directory/'record.json',frozen,reader.api[3](run))
            semantic=next(i for i in items if i['table']=='video_semantics')
            embedding=next(i for i in items if i['table']=='video_embeddings')
            self.assertEqual(semantic['payload']['category_selection'],selection)
            self.assertEqual(embedding['columns']['semantic_id'],semantic['key'])
            self.assertEqual(semantic['columns']['primary_category'],'unknown')
            record['category_selection']={**selection,'id':TAX['category_ids']['Comedy']}
            write(directory/'record.json',record)
            with self.assertRaisesRegex(ValueError,'category ID/name provenance mismatch'):
                complete_record(run,directory/'record.json',frozen)


if __name__=='__main__':unittest.main()
