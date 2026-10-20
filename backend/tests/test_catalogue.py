import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend.tests.test_video_data import fixture
from backend.video_data.artifacts import Reader, fingerprint
from backend.video_data.catalogue import (ORDER, category_resolution, compatible, changes,
    dump_backup, export_sql, key, load_package, prepare, row_from_entity, select_latest, timestamp, validate, verify_stage, write_package)
from backend.video_data.repository import Repository
from backend.video_data.__main__ import main as importer_main


class CatalogueTests(unittest.TestCase):
    def test_timestamps_use_actual_instant_and_require_timezone(self):
        self.assertEqual(timestamp('2026-10-17T05:00:00+05:00'),timestamp('2026-10-17T00:00:00Z'))
        with self.assertRaises(ValueError):timestamp('2026-10-17T00:00:00')
        with self.assertRaises(ValueError):timestamp('not-a-date')

    def test_latest_ignores_run_name_and_import_order(self):
        old={'id':'z','video_id':'V','run_id':'semantic_z99','payload':{'completed_at':'2026-10-17T05:00:00+05:00'}}
        new={'id':'a','video_id':'V','run_id':'semantic_a1','payload':{'completed_at':'2026-10-17T00:01:00Z'}}
        for rows in ([old,new],[new,old]):
            result,ties=select_latest(rows)
            self.assertEqual(result['V']['id'],'a');self.assertEqual(ties,[])

    def test_equal_completion_timestamps_require_review(self):
        rows=[{'id':n,'video_id':'V','payload':{'completed_at':t}} for n,t in
              [('a','2026-10-17T00:00:00Z'),('b','2026-10-17T05:00:00+05:00')]]
        result,ties=select_latest(rows)
        self.assertEqual(result,{});self.assertEqual(ties,['V'])

    def test_category_preserves_original_and_withholds_unverified_secondary(self):
        meta={'category_original':'Stand-up','category':'Comedy','source_manifest':'source.csv'}
        sem={'id':'s','payload':{'semantic':{'primary_category':'Education'}}}
        tax={'version':'v1','categories':{'Comedy':[],'Education':[],'unknown':[]}}
        before=copy.deepcopy(meta)
        result=category_resolution(meta,sem,{'Stand-up':'Comedy'},tax)
        self.assertEqual(result['original_label'],'Stand-up')
        self.assertEqual(result['effective_categories'],['Comedy'])
        self.assertEqual(result['secondary_categories'],[])
        self.assertEqual(result['secondary_status'],'withheld_unverified_evidence')
        self.assertEqual(meta,before)
        sem['payload']['semantic']['primary_category']='Comedy'
        self.assertEqual(category_resolution(meta,sem,{'Stand-up':'Comedy'},tax)['secondary_status'],'equivalent_deduplicated')

    def test_missing_category_reuses_qwen_without_fabricating_source(self):
        tax={'version':'v','categories':{'Comedy':[],'unknown':[]}}
        sem={'id':'s','payload':{'semantic':{'primary_category':'Comedy'}}}
        result=category_resolution({'category_original':''},sem,{},tax)
        self.assertEqual(result['provenance'],'existing_qwen')
        self.assertEqual(result['effective_categories'],['Comedy'])
        self.assertEqual(category_resolution({},None,{},tax)['provenance'],'missing')
        result=category_resolution({'category_original':'Unfamiliar real source label'},sem,{},tax)
        self.assertIsNone(result['primary_category'])
        self.assertEqual(result['original_label'],'Unfamiliar real source label')

    def graph(self, root):
        run,pred,metadata,directory=fixture(root)
        reader=Reader(root);frozen=reader.api[1](run/'frozen.json');rows=reader.api[3](run)
        items=reader.semantic_bundle(run,directory/'record.json',frozen,rows)
        tables={t:[] for t in ORDER}
        for item in items:tables[item['table']].append(row_from_entity(item))
        return tables,run,directory

    def test_graph_validation_and_incompatible_embeddings(self):
        with tempfile.TemporaryDirectory() as temp:
            tables,_,_=self.graph(Path(temp))
            self.assertEqual(validate(tables)['retrieval_ready'],1)
            for field in ['semantic_id','video_id','run_id','model','revision','template_version','input_hash']:
                bad=copy.deepcopy(tables);bad['video_embeddings'][0][field]='wrong'
                with self.assertRaises(ValueError):validate(bad)
            bad=copy.deepcopy(tables);bad['video_embeddings'][0]['embedding']=[0.0]*1024
            with self.assertRaises(ValueError):validate(bad)

    def test_projection_hash_and_cross_video_failures(self):
        with tempfile.TemporaryDirectory() as temp:
            tables,_,_=self.graph(Path(temp))
            for table,column in [('videos','content_hash'),('video_semantics','primary_category'),('video_context','transcript')]:
                bad=copy.deepcopy(tables);bad[table][0][column]='wrong'
                with self.assertRaises(ValueError):validate(bad)
            bad=copy.deepcopy(tables);bad['video_semantics'][0]['context_id']='missing'
            with self.assertRaises(ValueError):validate(bad)

    def test_semantics_without_embedding_reported_without_old_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            tables,_,_=self.graph(Path(temp));tables['video_embeddings']=[]
            report=validate(tables)
            self.assertEqual(report['retrieval_ready'],0)
            self.assertEqual(report['semantics_without_embedding'],1)

    def test_archive_checksum_and_complete_readback(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);tables,_,_=self.graph(root)
            path=root/'archive';write_package(path,tables,{'kind':'offline-stage'})
            loaded,_=load_package(path)
            self.assertEqual(loaded,{t:sorted(rs,key=lambda r:key(r,t)) for t,rs in tables.items()})
            self.assertEqual(validate(loaded),validate(tables))
            with self.assertRaises(FileExistsError):write_package(path,tables,{})
            with (path/'video_embeddings.jsonl').open('a') as stream:stream.write('\n')
            with self.assertRaises(ValueError):load_package(path)

    def test_prepare_is_offline_and_idempotent_and_preserves_payloads(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);tables,_,_=self.graph(root)
            snap=root/'snapshot';write_package(snap,tables,{'kind':'read-only-production-snapshot'})
            with patch('backend.video_data.catalogue.connect',side_effect=AssertionError('No database writes/network')):
                first=prepare(snap,root/'first',root,'imported')
                second=prepare(snap,root/'second',root,'imported')
            self.assertEqual(first,second)
            one,_=load_package(root/'first');two,_=load_package(root/'second')
            self.assertEqual(one,two)
            self.assertTrue(verify_stage(root/'first')['latest_selection_verified'])
            self.assertTrue(all(not d['insert'] and not d['remove'] for d in changes(one,two).values()))
            for t in ['videos','video_semantics','video_embeddings','affect_annotations','video_context']:
                self.assertEqual(one[t],tables[t])
            history,_=load_package(root/'first-history')
            self.assertEqual(history['video_semantics'],tables['video_semantics'])

    def test_multiple_current_semantics_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            tables,_,_=self.graph(Path(temp));second=copy.deepcopy(tables['video_semantics'][0]);second['id']='second'
            tables['video_semantics'].append(second)
            with self.assertRaises(ValueError):validate(tables)
            self.assertEqual(validate(tables,clean=False)['semantic_videos'],1)

    def test_legacy_importer_refuses_protected_clean_catalogue(self):
        with patch('backend.video_data.repository.inspect_schema',return_value={
                'columns':[{'schema':'public','table':'video_catalogue_current'}]}):
            with self.assertRaisesRegex(ValueError,'legacy historical sync is disabled'):
                Repository(object())

    def test_current_planner_rejects_live_apply(self):
        with patch('backend.video_data.config.connect',side_effect=AssertionError('Must not connect')):
            with self.assertRaises(SystemExit):
                importer_main(['sync','--current-only','--apply','--allow-live-writes'])

    def test_delta_refuses_payload_identity_rewrite(self):
        with tempfile.TemporaryDirectory() as temp:
            tables,_,_=self.graph(Path(temp));changed=copy.deepcopy(tables)
            changed['videos'][0]['payload']['category_original']='Changed'
            with self.assertRaisesRegex(ValueError,'Existing identity changed'):
                changes(tables,changed)

    def test_export_is_rollback_only_with_schema_and_snapshot_guards(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);tables,_,_=self.graph(root)
            catalog={k:[] for k in ['inbound_fks','triggers','indexes','constraints','security','policies','grants','extensions']}
            catalog['columns']=[{'table_name':t,'column_name':c} for t,rs in tables.items()
                                for c in (list(rs[0]) if rs else ['id'])]
            snap=root/'snapshot';write_package(snap,tables,{'kind':'read-only-production-snapshot','schema':'public'},
                                               {'catalog.json':catalog})
            prepare(snap,root/'stage',root,'imported')
            result=export_sql(snap,root/'stage',root/'sql')
            self.assertFalse(result['executed'])
            text=(root/'sql/replacement_rehearsal.sql').read_text(encoding='utf-8')
            self.assertTrue(text.endswith('ROLLBACK;\n'))
            self.assertNotIn('\nCOMMIT;',text)
            self.assertNotIn('DELETE FROM "public".',text)  # unchanged graph => no row writes
            self.assertIn('IN EXCLUSIVE MODE',text)
            self.assertIn('Schema/security changed:',text)
            self.assertIn('Production snapshot changed:',text)

    def test_native_backup_refuses_missing_tools_without_connecting(self):
        with patch('shutil.which',return_value=None), patch('backend.video_data.catalogue.connect',side_effect=AssertionError('No network')):
            with self.assertRaises(FileNotFoundError):dump_backup('must-not-be-created')

    def test_clean_context_and_affect_are_unique_per_video(self):
        with tempfile.TemporaryDirectory() as temp:
            tables,_,_=self.graph(Path(temp))
            for t in ['video_context','affect_annotations']:
                bad=copy.deepcopy(tables);duplicate=copy.deepcopy(bad[t][0]);duplicate['id']='duplicate'
                bad[t].append(duplicate)
                with self.assertRaisesRegex(ValueError,'Multiple current video records'):validate(bad)

    def test_views_preserve_incomplete_videos_and_are_backend_only(self):
        from backend.video_data.catalogue import category_views
        text=category_views('public')
        self.assertIn('video_catalogue_retrieval_ready',text)
        self.assertIn('video_catalogue_all',text)
        self.assertIn('matched.compatible_count=1',text)
        self.assertIn('LEFT JOIN "public".video_catalogue_current',text)
        self.assertIn('security_invoker=true',text)
        self.assertIn('FROM PUBLIC,anon,authenticated',text)
        self.assertIn('TO service_role',text)

    def test_repeated_clean_sync_has_no_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            tables,_,_=self.graph(Path(temp))
            self.assertTrue(all(not change['insert'] and not change['remove']
                                for change in changes(tables,tables).values()))


if __name__=='__main__':
    unittest.main()
